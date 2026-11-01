"""
장소 후기 읽기·쓰기(docs/credits-reviews.md 5절, 7절). 커밋하지 않는다 — 요청 세션(session_scope)이 한 번 커밋한다.

- 후기는 장소(place_id)에 붙는다. 어느 핀으로 왔는지는 라우터가 장소로 바꿔 넘긴다.
- 게스트 판정과 보상·잔액은 credits.api 한 곳(reject_guest, grant_review, get_balance). 숫자를 여기 적지 않는다.
- 숨긴 후기(hidden_at)는 목록·평균·개수·mine에서 빠지고, 신고할 수도 없다.
- 후기 글은 모델·로그로 보내지 않는다. 이 모듈은 로그를 남기지 않는다.
"""

import uuid

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from common.cursor import decode_cursor
from common.errors import AppError
from credits import api as credits_api
from pins import api as pins_api
from reviews import core
from reviews.constants import PAGE_SIZE, REVIEW_BODY_MAX
from reviews.models import Review, ReviewReport

_ROW_COLUMNS = (Review.id, Review.user_id, Review.rating, Review.body, Review.created_at, Review.updated_at)
_VISIBLE = Review.hidden_at.is_(None)


def _row(result) -> core.ReviewRow:
    return core.ReviewRow(id=result.id, user_id=result.user_id, rating=result.rating, body=result.body,
                          created_at=result.created_at, updated_at=result.updated_at)


def _summary(db: Session, place_id: str) -> dict:
    total, count = db.execute(
        select(func.coalesce(func.sum(Review.rating), 0), func.count()).where(Review.place_id == place_id, _VISIBLE)
    ).one()
    return {"average_rating": core.average(int(total), count), "count": count}


def list_page(db: Session, *, place_id: str, viewer_id: str, cursor: str | None) -> dict:
    """GET /pins/{pinId}/reviews — ReviewPage. 최신순(created_at, id 내림차순) PAGE_SIZE개. mine은 첫 쪽이든 아니든 싣는다."""
    query = select(*_ROW_COLUMNS).where(Review.place_id == place_id, _VISIBLE)
    if cursor:
        try:
            after = decode_cursor(cursor)
        except ValueError:
            raise AppError("VALIDATION_ERROR", "cursor 형식이 올바르지 않습니다") from None
        query = query.where(tuple_(Review.created_at, Review.id) < tuple_(*after))
    rows = [_row(r) for r in db.execute(
        query.order_by(Review.created_at.desc(), Review.id.desc()).limit(PAGE_SIZE + 1)
    ).all()]
    items, next_cursor = core.page(rows, viewer_id=viewer_id, page_size=PAGE_SIZE)

    result = {"summary": _summary(db, place_id), "limits": {"body_max": REVIEW_BODY_MAX}, "items": items}
    mine = db.execute(
        select(*_ROW_COLUMNS).where(Review.place_id == place_id, Review.user_id == viewer_id, _VISIBLE)
    ).first()
    if mine is not None:
        result["mine"] = core.my_review(_row(mine))
    if next_cursor is not None:
        result["next_cursor"] = next_cursor
    return result


def save_mine(db: Session, *, place_id: str, user_id: str, rating: int, body: str) -> dict:
    """PUT /pins/{pinId}/reviews/me — ReviewSaved. 게스트는 403. 새로 쓰면 같은 트랜잭션에서 credits.api.grant_review
    (그 장소에 처음이면 보상, 지웠다 다시 쓰면 원장 ref_id가 같아 0). 고치면 보상을 묻지 않는다(0).

    동시에 처음 쓰는 요청이 둘이면 INSERT ... ON CONFLICT DO NOTHING이 하나만 넣고, 다른 하나는 앞 요청이 끝난 뒤 수정으로 탄다.
    숨긴 후기를 고쳐도 숨김은 그대로다(숨김을 푸는 길은 관리 스크립트뿐)."""
    credits_api.reject_guest(db, user_id=user_id)
    inserted = db.execute(
        insert(Review).values(place_id=place_id, user_id=user_id, rating=rating, body=body)
        .on_conflict_do_nothing(index_elements=[Review.place_id, Review.user_id])
        .returning(*_ROW_COLUMNS)
    ).first()
    if inserted is not None:
        row = _row(inserted)
        credited = credits_api.grant_review(db, user_id=user_id, place_id=place_id)
    else:
        row = _row(db.execute(
            update(Review).where(Review.place_id == place_id, Review.user_id == user_id)
            .values(rating=rating, body=body, updated_at=func.now())
            .returning(*_ROW_COLUMNS)
        ).one())
        credited = 0
    return {"review": core.my_review(row), "credited": credited,
            "balance": credits_api.get_balance(db, user_id=user_id)}


def delete_mine(db: Session, *, place_id: str, user_id: str) -> None:
    """DELETE /pins/{pinId}/reviews/me — 내 후기가 없으면 404. 받은 크레딧은 그대로다. 신고 행은 FK CASCADE로 같이 지워진다.
    숨긴 후기는 작성자도 지울 수 없다(내 후기가 없는 것과 같은 404) — 지우고 다시 쓰면 숨김 없는 새 후기가 되어 관리자가 숨긴 글이
    되살아나기 때문이다(#972 검수). 다시 쓰면 save_mine이 숨긴 행을 고치므로 숨김이 유지된다."""
    deleted = db.execute(
        delete(Review).where(Review.place_id == place_id, Review.user_id == user_id, _VISIBLE)
    ).rowcount
    if deleted == 0:
        raise AppError("NOT_FOUND")


def report(db: Session, *, review_id: str, reporter_id: str) -> None:
    """POST /reviews/{reviewId}/reports — 후기마다 한 사람 한 번, 이미 신고했어도 조용히 성공(멱등).

    순서: 없거나 숨긴 후기 404 → 볼 수 없는 후기 404(그 장소를 가리키는 핀이 있는 지도의 구성원이 아님) → 게스트 403 →
    내 후기 422. 볼 수 없는 사람에게는 후기가 있는지도 알리지 않으려고 404를 먼저 본다(핀 경로의 guard와 같은 순서)."""
    try:
        target = uuid.UUID(review_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    review = db.execute(select(Review.place_id, Review.user_id).where(Review.id == target, _VISIBLE)).first()
    if review is None or not pins_api.has_place_pin_on_member_map(db, user_id=reporter_id, place_id=review.place_id):
        raise AppError("NOT_FOUND")
    credits_api.reject_guest(db, user_id=reporter_id)
    if review.user_id == reporter_id:
        raise AppError("VALIDATION_ERROR", "내 후기는 신고할 수 없습니다")
    db.execute(insert(ReviewReport).values(review_id=target, reporter_id=reporter_id).on_conflict_do_nothing())


def delete_reports_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴 — 그 사람이 한 신고를 지운다. 후기는 남긴다(작성자 이름은 원래 보이지 않는다). 지운 행 수."""
    return db.execute(delete(ReviewReport).where(ReviewReport.reporter_id == user_id)).rowcount

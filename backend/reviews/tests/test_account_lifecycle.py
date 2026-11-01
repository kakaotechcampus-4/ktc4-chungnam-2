"""후기와 계정 수명 — docs/credits-reviews.md 6절 계정 수명, 12절 24(탈퇴한 사람의 후기는 남는다).

탈퇴는 후기를 남기고 그 사람이 한 신고만 지운다(WITHDRAW_STEPS). 게스트 합치기는 옮길 것이 없다(MERGE_STEPS, no-op).
실제 auth.service를 태운다 — 탈퇴는 모든 모듈의 WITHDRAW_STEPS를 돈다.
"""

import uuid

from sqlalchemy import func, select

import main  # noqa: F401 — 탈퇴 단계가 모든 모듈 테이블을 건드린다(Base.metadata에 모두 등록)
from auth import service as auth_service
from reviews import api
from reviews.models import Review, ReviewReport


def _reports_by(db, user_id) -> int:
    return db.execute(select(func.count()).select_from(ReviewReport).where(ReviewReport.reporter_id == user_id)).scalar_one()


def test_withdraw_keeps_reviews_and_deletes_own_reports(world):
    a, b = world.user("a"), world.user("b")
    map_id = world.map(a, b)
    place_id = world.place()
    pin_id = world.pin(map_id, place_id, by=a)
    by_a = world.review(place_id, a, body="a가 쓴 글")
    by_b = world.review(place_id, b, body="b가 쓴 글")
    world.db.add_all([ReviewReport(review_id=uuid.UUID(by_a), reporter_id=b),
                      ReviewReport(review_id=uuid.UUID(by_b), reporter_id=a)])
    world.db.flush()

    auth_service.withdraw_user(world.db, user_id=b)

    assert world.db.get(Review, uuid.UUID(by_b)) is not None          # b가 쓴 후기는 남는다
    assert _reports_by(world.db, b) == 0                                # b가 한 신고는 지워진다
    assert _reports_by(world.db, a) == 1                                # 남이 b의 후기에 한 신고는 남는다
    page = world.client(a).get(f"/pins/{pin_id}/reviews").json()
    assert {i["id"] for i in page["items"]} == {by_a, by_b}


def test_delete_reports_by_user_counts_rows(world):
    a, b = world.user("a"), world.user("b")
    place_id = world.place()
    review_id = uuid.UUID(world.review(place_id, a))
    world.db.add(ReviewReport(review_id=review_id, reporter_id=b))
    world.db.flush()

    assert api.delete_reports_by_user(world.db, user_id=b) == 1
    assert api.delete_reports_by_user(world.db, user_id=b) == 0


def test_reassign_user_moves_nothing(world):
    a, b = world.user("a"), world.user("b")
    review_id = world.review(world.place(), a)

    assert api.reassign_user(world.db, from_user_id=a, to_user_id=b) == {"reviews": 0, "review_reports": 0}
    assert world.db.get(Review, uuid.UUID(review_id)).user_id == a

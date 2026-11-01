"""docs/api-spec.yaml `reviews` 태그 — 장소 후기 4개 경로(#432, #951). 모두 로그인 필요.

핀 경로 셋은 authz.guard로 그 핀의 지도 구성원만 통과시킨다(비구성원 404). 조회 전용 액션이 없어 pins 라우터의 PinToRead와 같이
멤버 액션 하나(pin.react)를 빌린다 — 새 권한 액션을 만들지 않는다(명세 7절). 장소를 찾은 뒤 실시간 핀은 422 PLACE_NOT_SUPPORTED.
신고 경로는 지도가 하나로 정해지지 않아 guard 대신 service.report가 pins.api로 「볼 수 있는 후기인가」를 본다.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.guard import require
from common.database import get_db_session
from reviews import core, service
from reviews.loaders import load_review_pin
from reviews.schemas import ReviewPage, ReviewSaved, ReviewUpsertRequest

router = APIRouter(tags=["reviews"], dependencies=[Depends(get_current_user)])

PinForReviews = Depends(require("pin.react", load_review_pin))   # 핀 조회와 같은 규칙 — 비구성원 404
DbSession = Depends(get_db_session)


@router.get("/pins/{pinId}/reviews", response_model=ReviewPage, response_model_exclude_unset=True)
def get_reviews(
    cursor: str | None = Query(default=None),
    pin=PinForReviews,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    place_id = core.place_of(pin.source, pin.place_id)
    return service.list_page(db, place_id=place_id, viewer_id=user.user_id, cursor=cursor)


@router.put("/pins/{pinId}/reviews/me", response_model=ReviewSaved)
def put_my_review(
    body: ReviewUpsertRequest,
    pin=PinForReviews,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    place_id = core.place_of(pin.source, pin.place_id)
    return service.save_mine(db, place_id=place_id, user_id=user.user_id, rating=body.rating, body=body.body)


@router.delete("/pins/{pinId}/reviews/me", status_code=204)
def delete_my_review(
    pin=PinForReviews,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    place_id = core.place_of(pin.source, pin.place_id)
    service.delete_mine(db, place_id=place_id, user_id=user.user_id)
    return Response(status_code=204)


@router.post("/reviews/{reviewId}/reports", status_code=204)
def post_report(
    reviewId: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    service.report(db, review_id=reviewId, reporter_id=user.user_id)
    return Response(status_code=204)

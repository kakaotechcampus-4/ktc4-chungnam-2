"""docs/api-spec.yaml의 feedback 태그 — POST /feedback (#10). 로그인만 필요하다.
검증(422) → 호출 상한(429) → 저장 순서다 — 잘못된 요청이 상한을 쓰지 않는다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from feedback import api, service
from feedback.schemas import FeedbackReceipt, FeedbackRequest

router = APIRouter(tags=["feedback"])


@router.post("/feedback", status_code=201, response_model=FeedbackReceipt)
def post_feedback(
    body: FeedbackRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    service.clean_message(body.message)
    api.check_submit_rate(user.user_id)
    return service.submit(db, user_id=user.user_id, message=body.message, category=body.category, map_id=body.map_id)

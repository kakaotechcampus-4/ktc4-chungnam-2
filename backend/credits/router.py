"""docs/api-spec.yaml `credits` 태그 — GET /credits/me (#432). 로그인만 필요하고, 게스트는 403 GUEST_NOT_ALLOWED.
이 요청은 쓰지 않는다 — 계정 행이 없으면 처음 지급량을 돌려준다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from credits import service
from credits.schemas import CreditBalance

router = APIRouter(tags=["credits"])


@router.get("/credits/me", response_model=CreditBalance)
def get_my_credits(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    return service.get_my_credits(db, user_id=user.user_id)

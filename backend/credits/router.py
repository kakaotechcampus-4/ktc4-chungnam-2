"""docs/api-spec.yaml `credits` 태그 (#432, #1038). 로그인만 필요하고, 게스트는 403 GUEST_NOT_ALLOWED.

- GET /credits/me — 쓰지 않는다. 계정 행이 없으면 처음 지급량을 돌려준다. `ad`는 광고 보고 충전(명세 3.7).
- POST /credits/ad-sessions, POST /credits/ad-sessions/{adSessionId}/claim — 광고 보고 충전(명세 3.7).

시각은 요청마다 여기서 한 번 만들어 넘긴다(하루 경계, 세션 시각 — 테스트는 service에 주입한다).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from credits import service
from credits.schemas import AdClaim, AdSession, CreditBalance

router = APIRouter(tags=["credits"])


@router.get("/credits/me", response_model=CreditBalance)
def get_my_credits(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    return service.get_my_credits(db, user_id=user.user_id, now=datetime.now(timezone.utc))


@router.post("/credits/ad-sessions", response_model=AdSession, status_code=201)
def open_ad_session(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    return service.open_ad_session(db, user_id=user.user_id, now=datetime.now(timezone.utc))


@router.post("/credits/ad-sessions/{ad_session_id}/claim", response_model=AdClaim)
def claim_ad_session(
    ad_session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    return service.claim_ad_session(db, user_id=user.user_id, ad_session_id=ad_session_id,
                                    now=datetime.now(timezone.utc))

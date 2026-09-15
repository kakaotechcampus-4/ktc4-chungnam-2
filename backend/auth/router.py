"""
docs/api-spec.yaml `auth` 태그 4개 엔드포인트.

`/auth/kakao/callback`은 로그인 전 콜백이라 인증 의존성이 없는 별도 라우터
(`public_router`)에 둔다 — 전역 `security: [cookieAuth]`가 이 경로에는 적용되면 안 된다는
점은 이미 `mentor-review-plan.md`가 결정했지만, `docs/api-spec.yaml:28-38`에는 아직
`security: []`가 반영돼 있지 않다(auth/for_Root.md "루트 확인·결정 필요" 1번, 이번에도
재확인함 — YAML은 손대지 않고 라우터 배선으로만 실제 동작을 맞춘다).

나머지 3개(`/me`, `/logout`, `/withdraw`)는 `router`에 묶는다 — `dependencies=[Depends(
get_current_user)]`가 라우터 선언 자체에 박혀 있어 개별 엔드포인트가 인증을 따로 기억할
필요가 없다(mentor-review-plan.md "사용 규약").
"""

import time

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from auth import core, service
from auth.deps import DbSession, get_current_user
from auth.schemas import CurrentUser, UserResponse
from common.settings import settings

SESSION_COOKIE = "session"

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(get_current_user)])


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = core.create_session_token(user_id, secret=settings.session_secret, issued_at=int(time.time()))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=core.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.is_prod,  # dev(http://localhost)에서는 Secure 쿠키가 저장되지 않는다
        samesite="lax",
    )


@public_router.get("/kakao/callback")
def get_kakao_callback(code: str = Query(...), db: Session = DbSession):
    user = service.login_with_kakao_code(db, code=code)
    redirect = RedirectResponse(url=settings.frontend_login_redirect_url, status_code=302)
    _set_session_cookie(redirect, user.id)
    return redirect


@router.get("/me", response_model=UserResponse)
def get_me(user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    row = service.get_active_user_or_401(db, user_id=user.user_id)
    return UserResponse(id=row.id, display_name=row.display_name)


@router.post("/logout", status_code=204)
def post_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)


@router.post("/withdraw", status_code=204)
def post_withdraw(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    service.withdraw_user(db, user_id=user.user_id)
    response.delete_cookie(SESSION_COOKIE)

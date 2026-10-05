"""
docs/api-spec.yaml `auth` 태그 4개 엔드포인트.

`/auth/kakao/login`·`/auth/kakao/callback`은 로그인 전 경로라 인증 의존성이 없는 별도 라우터
(`public_router`)에 둔다 — 전역 `security: [cookieAuth]`가 이 경로에는 적용되면 안 된다는
점은 이미 `mentor-review-plan.md`가 결정했지만, `docs/api-spec.yaml:28-38`에는 아직
`security: []`가 반영돼 있지 않다(auth/for_Root.md "루트 확인·결정 필요" 1번, 이번에도
재확인함 — YAML은 손대지 않고 라우터 배선으로만 실제 동작을 맞춘다).

나머지 3개(`/me`, `/logout`, `/withdraw`)는 `router`에 묶는다 — `dependencies=[Depends(
get_current_user)]`가 라우터 선언 자체에 박혀 있어 개별 엔드포인트가 인증을 따로 기억할
필요가 없다(mentor-review-plan.md "사용 규약").
"""

import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Cookie, Depends, Query, Response
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from auth import core, service
from auth.deps import DbSession, get_current_user
from auth.schemas import CurrentUser, UserResponse, UserUpdateRequest
from common.errors import AppError
from common.settings import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session"
STATE_COOKIE = "kakao_oauth_state"
# 콜백(/auth/kakao/callback)에만 실리면 되므로 경로를 좁힌다. 지울 때도 같은 경로여야 지워진다.
STATE_COOKIE_PATH = "/auth/kakao"

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


def _clear_state_cookie(response: Response) -> None:
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)


@public_router.get("/kakao/login")
def get_kakao_login():
    """로그인 시작 — state를 만들어 서명한 HttpOnly 쿠키에 넣고 같은 값을 붙여 카카오 인가 화면으로 보낸다.
    콜백에서 이 쿠키와 대조하므로, 다른 브라우저에서 시작된 로그인의 콜백 링크는 통하지 않는다(로그인 CSRF)."""
    if not settings.kakao_client_id or not settings.kakao_redirect_uri:
        # 비어 있는 채로 카카오에 보내면 카카오 오류 화면만 뜨고 원인이 안 보인다 — 여기서 드러낸다.
        raise AppError("INTERNAL_ERROR", "카카오 로그인 설정(KAKAO_CLIENT_ID, KAKAO_REDIRECT_URI)이 비어 있습니다")
    state = core.new_state()
    redirect = RedirectResponse(
        url=core.kakao_authorize_url(
            client_id=settings.kakao_client_id, redirect_uri=settings.kakao_redirect_uri, state=state,
        ),
        status_code=302,
    )
    redirect.set_cookie(
        STATE_COOKIE,
        core.create_state_cookie_value(state, secret=settings.session_secret, issued_at=int(time.time())),
        max_age=core.STATE_TTL_SECONDS,
        path=STATE_COOKIE_PATH,
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",   # 카카오에서 콜백으로 돌아오는 건 최상위 GET 이동이라 Lax 쿠키가 같이 온다
    )
    return redirect


def _login_redirect(*, error: str | None = None) -> RedirectResponse:
    """진입점으로 302. 실패면 `login_error`를 붙이고(주소에 있던 쿼리·조각은 보존), state 쿠키는 어느 쪽이든 지운다."""
    url = settings.frontend_login_redirect_url
    if error is not None:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "login_error"]
        url = urlunsplit(parts._replace(query=urlencode(query + [("login_error", error)])))
    redirect = RedirectResponse(url=url, status_code=302)
    _clear_state_cookie(redirect)
    return redirect


@public_router.get("/kakao/callback")
def get_kakao_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias=STATE_COOKIE),
    db: Session = DbSession,
):
    """브라우저가 카카오에서 돌아오는 이동이라 성공이든 실패든 항상 302다(JSON을 돌려주면 사용자가 그대로 본다).
    실패는 진입점에 `?login_error=`로 알린다(cancelled·invalid_state·kakao_failed·server_error) — 실패를
    로그인 성공처럼 넘기지 않는다. state 검증이 먼저다: 위조된 요청에는 카카오를 부르지 않는다.
    성공이든 실패든 state 쿠키를 지워 같은 콜백 링크를 다시 쓸 수 없게 한다."""
    if not core.verify_state(state_cookie, state, secret=settings.session_secret, now=int(time.time())):
        return _login_redirect(error="invalid_state")
    if error is not None or not code:
        return _login_redirect(error="cancelled")
    try:
        user = service.login_with_kakao_code(db, code=code)
    except service.KakaoApiError as exc:
        logger.warning("kakao login failed: reason=%s kakao_status=%s", exc.detail.get("reason"), exc.detail.get("kakao_status"))
        return _login_redirect(error="kakao_failed")
    except Exception as exc:  # noqa: BLE001 — 사용자는 어떤 실패든 JSON 대신 진입점으로 돌아가야 한다
        logger.error("kakao login failed: %s", type(exc).__name__)   # 종류만 — 메시지에 토큰·프로필이 섞일 수 있다
        db.rollback()   # 실패한 요청이 만든 반쪽 상태를 커밋하지 않는다
        return _login_redirect(error="server_error")
    redirect = _login_redirect()
    _set_session_cookie(redirect, user.id)
    return redirect


@router.get("/me", response_model=UserResponse)
def get_me(user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    row = service.get_active_user_or_401(db, user_id=user.user_id)
    return UserResponse(id=row.id, display_name=row.display_name)


@router.patch("/me", response_model=UserResponse)
def patch_me(body: UserUpdateRequest, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    row = service.update_display_name(db, user_id=user.user_id, display_name=body.display_name)
    return UserResponse(id=row.id, display_name=row.display_name)


@router.post("/logout", status_code=204)
def post_logout(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    service.revoke_sessions(db, user_id=user.user_id)
    response.delete_cookie(SESSION_COOKIE)


@router.post("/withdraw", status_code=204)
def post_withdraw(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    service.withdraw_user(db, user_id=user.user_id)
    response.delete_cookie(SESSION_COOKIE)

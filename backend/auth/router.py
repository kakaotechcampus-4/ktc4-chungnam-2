"""
docs/api-spec.yaml `auth` 태그 4개 엔드포인트.

`/auth/{kakao|google}/login`·`/callback`은 로그인 전 경로라 인증 의존성이 없는 별도 라우터
(`public_router`)에 둔다 — 전역 `security: [cookieAuth]`가 이 경로에는 적용되면 안 된다는
점은 `docs/api-spec.yaml`의 두 경로에 `security: []`로 적혀 있다(PR #71 멘토 리뷰).

나머지 3개(`/me`, `/logout`, `/withdraw`)는 `router`에 묶는다 — `dependencies=[Depends(
get_current_user)]`가 라우터 선언 자체에 박혀 있어 개별 엔드포인트가 인증을 따로 기억할
필요가 없다(mentor-review-plan.md "사용 규약").
"""

import logging
import time
from typing import Callable, NamedTuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from auth import core, service
from auth.deps import DbSession, get_current_user
from auth.schemas import (
    CurrentUser, GuestJoinRequest, GuestJoinResult, PendingAccount, PendingChoiceRequest, UserResponse, UserUpdateRequest,
)
from common.errors import AppError
from common.ratelimit import SlidingWindowLimiter
from common.settings import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session"
STATE_COOKIE = "kakao_oauth_state"
GOOGLE_STATE_COOKIE = "google_oauth_state"
PENDING_COOKIE = "pending_account"


class _Provider(NamedTuple):
    """로그인 제공자 하나 — 시작·콜백 흐름(state 쿠키, 게스트 합치기, 탈퇴 계정 선택)은 같고 이 값만 다르다(#1514)."""
    name: str
    client_id: str
    redirect_uri: str
    state_cookie: str
    authorize_url: Callable[..., str]
    login: Callable
    login_guest: Callable


def _kakao() -> _Provider:
    return _Provider("kakao", settings.kakao_client_id, settings.kakao_redirect_uri, STATE_COOKIE,
                     core.kakao_authorize_url, service.login_with_kakao_code, service.login_guest_with_kakao_code)


def _google() -> _Provider:
    return _Provider("google", settings.google_client_id, settings.google_redirect_uri, GOOGLE_STATE_COOKIE,
                     core.google_authorize_url, service.login_with_google_code, service.login_guest_with_google_code)

# IP당 시간당 게스트 가입 시도 상한(인메모리, 인스턴스마다 센다). 성공·실패 모두 센다.
GUEST_JOIN_PER_HOUR = 10
guest_join_limiter = SlidingWindowLimiter(GUEST_JOIN_PER_HOUR, window_s=3600.0)

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(get_current_user)])


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = core.create_session_token(user_id, secret=settings.session_secret, issued_at=int(time.time()))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=core.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,  # dev(http://localhost)에서는 Secure 쿠키가 저장되지 않는다(COOKIE_SECURE, #810)
        samesite="lax",
    )


def _clear_state_cookie(response: Response, provider: _Provider) -> None:
    # 심을 때와 같은 경로여야 지워진다
    response.delete_cookie(provider.state_cookie, path=core.state_cookie_path(provider.redirect_uri))


@public_router.get("/kakao/login")
def get_kakao_login(session: str | None = Cookie(default=None), db: Session = DbSession):
    """로그인 시작 — state를 만들어 서명한 HttpOnly 쿠키에 넣고 같은 값을 붙여 카카오 인가 화면으로 보낸다.
    콜백에서 이 쿠키와 대조하므로, 다른 브라우저에서 시작된 로그인의 콜백 링크는 통하지 않는다(로그인 CSRF)."""
    if not settings.kakao_client_id or not settings.kakao_redirect_uri:
        # 비어 있는 채로 카카오에 보내면 카카오 오류 화면만 뜨고 원인이 안 보인다 — 여기서 드러낸다.
        raise AppError("INTERNAL_ERROR", "카카오 로그인 설정(KAKAO_CLIENT_ID, KAKAO_REDIRECT_URI)이 비어 있습니다")
    return _start_login(_kakao(), session, db)


@public_router.get("/google/login")
def get_google_login(session: str | None = Cookie(default=None), db: Session = DbSession):
    """구글 로그인 시작(#1514) — 카카오와 같은 흐름이다. 키가 비어 있으면 서버 오류 대신 진입점에
    `login_error=google_unavailable`로 돌려보낸다 — 카카오와 달리 구글은 아직 켜지 않은 환경이 있다."""
    provider = _google()
    if not provider.client_id or not provider.redirect_uri:
        return _login_redirect(provider, error="google_unavailable")
    return _start_login(provider, session, db)


def _start_login(provider: _Provider, session: str | None, db: Session) -> RedirectResponse:
    state = core.new_state()
    redirect = RedirectResponse(
        url=provider.authorize_url(client_id=provider.client_id, redirect_uri=provider.redirect_uri, state=state),
        status_code=302,
    )
    redirect.set_cookie(
        provider.state_cookie,
        core.create_state_cookie_value(
            state, secret=settings.session_secret, issued_at=int(time.time()),
            guest_user_id=service.live_guest_id_for_session(db, session),
        ),
        max_age=core.STATE_TTL_SECONDS,
        path=core.state_cookie_path(provider.redirect_uri),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",   # 제공자에서 콜백으로 돌아오는 건 최상위 GET 이동이라 Lax 쿠키가 같이 온다
    )
    return redirect


def _pending_cookie_path() -> str:
    # 카카오·구글 콜백이 같은 `/auth` 아래라 어느 쪽으로 구해도 같다 — 다르면 설정이 서버 시작에서 막는다(common/settings.py)
    return core.pending_cookie_path(settings.kakao_redirect_uri or settings.google_redirect_uri)


def _clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(PENDING_COOKIE, path=_pending_cookie_path())   # 심을 때와 같은 경로여야 지워진다


def _login_redirect(
    provider: _Provider, *, error: str | None = None, guest_merged: bool | None = None, login_pending: str | None = None,
) -> RedirectResponse:
    """진입점으로 302. 실패면 `login_error`, 게스트 전환이면 `guest_merged`, 탈퇴 계정 선택 대기면 `login_pending`을
    붙이고(주소에 있던 쿼리·조각은 보존, 같은 이름의 값만 대체), state 쿠키는 어느 쪽이든 지운다."""
    url = settings.frontend_login_redirect_url
    added = []
    if error is not None:
        added.append(("login_error", error))
    if login_pending is not None:
        added.append(("login_pending", login_pending))
    if guest_merged is not None:
        added.append(("guest_merged", "true" if guest_merged else "false"))
    if added:
        parts = urlsplit(url)
        names = {k for k, _ in added}
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in names]
        url = urlunsplit(parts._replace(query=urlencode(query + added)))
    redirect = RedirectResponse(url=url, status_code=302)
    _clear_state_cookie(redirect, provider)
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
    return _finish_login(_kakao(), code=code, state=state, error=error, state_cookie=state_cookie, db=db)


@public_router.get("/google/callback")
def get_google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias=GOOGLE_STATE_COOKIE),
    db: Session = DbSession,
):
    """구글 콜백(#1514) — 카카오 콜백과 같은 규칙이다. 제공자 실패는 `login_error=google_failed`."""
    return _finish_login(_google(), code=code, state=state, error=error, state_cookie=state_cookie, db=db)


def _finish_login(
    provider: _Provider, *, code: str | None, state: str | None, error: str | None, state_cookie: str | None, db: Session,
) -> RedirectResponse:
    state_claims = core.parse_state(state_cookie, state, secret=settings.session_secret, now=int(time.time()))
    if state_claims is None:
        return _login_redirect(provider, error="invalid_state")
    if error is not None or not code:
        return _login_redirect(provider, error="cancelled")
    try:
        if state_claims.guest_user_id:   # 게스트가 시작한 로그인 — 로그인 수단을 붙이거나 기록을 합친다. 실패해도 로그인은 성공이다(#560, #694)
            user, guest_merged = provider.login_guest(db, code=code, guest_user_id=state_claims.guest_user_id)
        else:
            user, guest_merged = provider.login(db, code=code), None
    except service.WithdrawnAccountPending as pending:
        # 복구 기간 안의 탈퇴 계정 — 세션을 만들지 않고 선택 대기 쿠키만 내린다. 게스트가 시작했어도 기록은 합치지 않는다(#855)
        redirect = _login_redirect(
            provider, login_pending="withdrawn_account", guest_merged=False if state_claims.guest_user_id else None,
        )
        redirect.set_cookie(
            PENDING_COOKIE,
            core.create_pending_cookie_value(
                pending.user.id, pending.provider, pending.user.deleted_at,
                secret=settings.session_secret, issued_at=int(time.time()),
            ),
            max_age=core.PENDING_TTL_SECONDS,
            path=_pending_cookie_path(),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        return redirect
    except service.OAuthProviderError as exc:
        status_key = f"{provider.name}_status"
        logger.warning(
            "%s login failed: reason=%s %s=%s", provider.name, exc.detail.get("reason"), status_key, exc.detail.get(status_key),
        )
        return _login_redirect(provider, error=f"{provider.name}_failed")
    except Exception as exc:  # noqa: BLE001 — 사용자는 어떤 실패든 JSON 대신 진입점으로 돌아가야 한다
        logger.error("%s login failed: %s", provider.name, type(exc).__name__)   # 종류만 — 메시지에 토큰·프로필이 섞일 수 있다
        db.rollback()   # 실패한 요청이 만든 반쪽 상태를 커밋하지 않는다
        return _login_redirect(provider, error="server_error")
    redirect = _login_redirect(provider, guest_merged=guest_merged)
    _set_session_cookie(redirect, user.id)
    return redirect


def _pending_claims(pending_cookie: str | None) -> core.PendingClaims:
    claims = core.parse_pending_cookie(pending_cookie, secret=settings.session_secret, now=int(time.time()))
    if claims is None:
        raise AppError("NO_PENDING_LOGIN")
    return claims


@public_router.get("/pending", response_model=PendingAccount)
def get_pending(pending_cookie: str | None = Cookie(default=None, alias=PENDING_COOKIE), db: Session = DbSession):
    """탈퇴한 계정으로 로그인하려는 중의 안내(#855) — 세션 없이 콜백이 내린 선택 대기 쿠키로 부른다."""
    return service.get_pending_account(db, claims=_pending_claims(pending_cookie))


@public_router.post("/pending", response_model=UserResponse)
def post_pending(
    body: PendingChoiceRequest, request: Request, response: Response,
    pending_cookie: str | None = Cookie(default=None, alias=PENDING_COOKIE), db: Session = DbSession,
):
    """선택(#855): `restart`는 새 계정(201), `restore`는 기존 계정 되살리기(200). 둘 다 세션을 내리고 선택 대기 쿠키를 지운다.
    본문은 application/json만 받는다 — 헤더 없는 교차 사이트 POST가 쿠키를 싣고 오지 못하게 SameSite=Lax와 함께 막는다."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise AppError("VALIDATION_ERROR", "본문은 application/json이어야 합니다")
    claims = _pending_claims(pending_cookie)
    if body.choice == "restore":
        row = service.restore_account(db, claims=claims)
    else:
        row = service.restart_account(db, claims=claims)
        response.status_code = 201
    _set_session_cookie(response, row.id)
    _clear_pending_cookie(response)
    return _user_response(row)


@public_router.post("/guest", response_model=GuestJoinResult, response_model_exclude_none=True, status_code=201)
def post_guest(body: GuestJoinRequest, request: Request, response: Response, db: Session = DbSession):
    """이름만 입력해 초대받은 지도에 들어간다(#472) — 로그인 전 호출. 계정 생성·지도 가입·세션 쿠키가 한 요청이다.
    쿠키·초대 토큰·이름은 로그에 남기지 않는다."""
    client_ip = request.client.host if request.client else "unknown"
    if not guest_join_limiter.allow(client_ip):
        raise AppError("RATE_LIMITED")
    row, map_ = service.join_as_guest(db, display_name=body.display_name, invite_token=body.invite_token)
    _set_session_cookie(response, row.id)
    return GuestJoinResult(user=_user_response(row), map=map_)


def _user_response(row) -> UserResponse:
    return UserResponse(id=row.id, display_name=row.display_name, is_guest=row.is_guest)


@router.get("/me", response_model=UserResponse)
def get_me(user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    row = service.get_active_user_or_401(db, user_id=user.user_id)
    return _user_response(row)


@router.patch("/me", response_model=UserResponse)
def patch_me(body: UserUpdateRequest, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    row = service.update_display_name(db, user_id=user.user_id, display_name=body.display_name)
    return _user_response(row)


@router.post("/logout", status_code=204)
def post_logout(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    service.revoke_sessions(db, user_id=user.user_id)
    response.delete_cookie(SESSION_COOKIE)


@router.post("/withdraw", status_code=204)
def post_withdraw(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = DbSession):
    service.withdraw_user(db, user_id=user.user_id)
    response.delete_cookie(SESSION_COOKIE)

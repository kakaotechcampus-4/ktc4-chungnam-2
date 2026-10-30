"""
docs/api-spec.yaml `auth` 태그 4개 엔드포인트.

`/auth/kakao/login`·`/auth/kakao/callback`은 로그인 전 경로라 인증 의존성이 없는 별도 라우터
(`public_router`)에 둔다 — 전역 `security: [cookieAuth]`가 이 경로에는 적용되면 안 된다는
점은 `docs/api-spec.yaml`의 두 경로에 `security: []`로 적혀 있다(PR #71 멘토 리뷰).

나머지 3개(`/me`, `/logout`, `/withdraw`)는 `router`에 묶는다 — `dependencies=[Depends(
get_current_user)]`가 라우터 선언 자체에 박혀 있어 개별 엔드포인트가 인증을 따로 기억할
필요가 없다(mentor-review-plan.md "사용 규약").
"""

import logging
import time
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
PENDING_COOKIE = "pending_account"

# IP당 시간당 게스트 가입 시도 상한(인메모리, 인스턴스마다 센다). 성공·실패 모두 센다.
GUEST_JOIN_PER_HOUR = 10
guest_join_limiter = SlidingWindowLimiter(GUEST_JOIN_PER_HOUR, window_s=3600.0)

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(get_current_user)])


def _set_session_cookie(response: Response, user_id: str, *, sessions_valid_after=None) -> None:
    token = core.create_session_token(
        user_id, secret=settings.session_secret,
        issued_at=core.new_session_issued_at(int(time.time()), sessions_valid_after),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=core.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.is_prod,  # dev(http://localhost)에서는 Secure 쿠키가 저장되지 않는다
        samesite="lax",
    )


def _clear_state_cookie(response: Response) -> None:
    # 심을 때와 같은 경로여야 지워진다
    response.delete_cookie(STATE_COOKIE, path=core.state_cookie_path(settings.kakao_redirect_uri))


@public_router.get("/kakao/login")
def get_kakao_login(session: str | None = Cookie(default=None), db: Session = DbSession):
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
        core.create_state_cookie_value(
            state, secret=settings.session_secret, issued_at=int(time.time()),
            guest_user_id=service.live_guest_id_for_session(db, session),
        ),
        max_age=core.STATE_TTL_SECONDS,
        path=core.state_cookie_path(settings.kakao_redirect_uri),
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",   # 카카오에서 콜백으로 돌아오는 건 최상위 GET 이동이라 Lax 쿠키가 같이 온다
    )
    return redirect


def _pending_cookie_path() -> str:
    return core.pending_cookie_path(settings.kakao_redirect_uri)


def _clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(PENDING_COOKIE, path=_pending_cookie_path())   # 심을 때와 같은 경로여야 지워진다


def _login_redirect(
    *, error: str | None = None, guest_merged: bool | None = None, login_pending: str | None = None,
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
    state_claims = core.parse_state(state_cookie, state, secret=settings.session_secret, now=int(time.time()))
    if state_claims is None:
        return _login_redirect(error="invalid_state")
    if error is not None or not code:
        return _login_redirect(error="cancelled")
    try:
        if state_claims.guest_user_id:   # 게스트가 시작한 로그인 — 카카오 수단을 붙이거나 기록을 합친다. 실패해도 로그인은 성공이다(#560, #694)
            user, guest_merged = service.login_guest_with_kakao_code(
                db, code=code, guest_user_id=state_claims.guest_user_id,
            )
        else:
            user, guest_merged = service.login_with_kakao_code(db, code=code), None
    except service.WithdrawnAccountPending as pending:
        # 복구 기간 안의 탈퇴 계정 — 세션을 만들지 않고 선택 대기 쿠키만 내린다. 게스트가 시작했어도 기록은 합치지 않는다(#855)
        redirect = _login_redirect(
            login_pending="withdrawn_account", guest_merged=False if state_claims.guest_user_id else None,
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
            secure=settings.is_prod,
            samesite="lax",
        )
        return redirect
    except service.KakaoApiError as exc:
        logger.warning("kakao login failed: reason=%s kakao_status=%s", exc.detail.get("reason"), exc.detail.get("kakao_status"))
        return _login_redirect(error="kakao_failed")
    except Exception as exc:  # noqa: BLE001 — 사용자는 어떤 실패든 JSON 대신 진입점으로 돌아가야 한다
        logger.error("kakao login failed: %s", type(exc).__name__)   # 종류만 — 메시지에 토큰·프로필이 섞일 수 있다
        db.rollback()   # 실패한 요청이 만든 반쪽 상태를 커밋하지 않는다
        return _login_redirect(error="server_error")
    redirect = _login_redirect(guest_merged=guest_merged)
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
    _set_session_cookie(response, row.id, sessions_valid_after=row.sessions_valid_after)
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

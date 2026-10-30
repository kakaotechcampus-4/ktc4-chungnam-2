"""
순수 함수만 — I/O 없음(docs/code-quality.md 기능형 코어). 세션 토큰 서명/검증과 카카오 프로필
파싱은 전부 입력을 받아 값을 반환할 뿐이라 여기 둔다. DB·HTTP 호출은 auth/service.py(셸)로.
"""

import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlencode, urlsplit

KAKAO_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
STATE_TTL_SECONDS = 60 * 10  # 로그인 시작 → 카카오 동의 → 콜백까지 걸리는 시간. 짧게 둔다.
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30일. 세션 테이블이 없어(data-model.md) 무상태 토큰의 자체 만료로 대신한다.


class SessionClaims(NamedTuple):
    user_id: str
    issued_at: int


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(user_id: str, *, secret: str, issued_at: int) -> str:
    """`user_id.발급시각.서명` 형태의 무상태 서명 토큰. httpOnly 쿠키 값으로 그대로 들어간다
    (최종기획안 13절 "토큰을 프론트에 두지 않는다" — 값 자체는 프론트 JS가 못 읽지만, 세션을
    DB에 두지 않기로 한 결정과는 별개 사안이다)."""
    payload = f"{user_id}.{issued_at}"
    return f"{payload}.{_sign(payload, secret)}"


def parse_session_token(token: str, *, secret: str, now: int, ttl_seconds: int = SESSION_TTL_SECONDS) -> SessionClaims | None:
    """서명·형식·만료를 확인해 (user_id, 발급 시각)을 돌려준다. 뭐가 문제든 조용히 None만 반환한다 —
    호출부(auth/deps.py)가 이걸 UNAUTHORIZED로 바꾸는 게 유일한 책임이라, 여기서 어떤 조합이
    실패인지 구분해 알려줄 필요가 없다(실패 사유를 노출하면 토큰 위조 시도에 오라클을 주는 셈)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id, issued_at_raw, signature = parts
    if not user_id or not issued_at_raw.isdigit():
        return None
    payload = f"{user_id}.{issued_at_raw}"
    if not hmac.compare_digest(_sign(payload, secret), signature):
        return None
    issued_at = int(issued_at_raw)
    if now < issued_at or now - issued_at > ttl_seconds:
        return None
    return SessionClaims(user_id, issued_at)


# ---- OAuth state (로그인 CSRF 방지, #128) ----
# 서명 대상에 용도 문자열을 넣어 세션 토큰과 서로 대체되지 않게 한다 — 세션 토큰의 서명 대상은
# `user_id.발급시각`이라 어느 쪽이든 상대 서명 검증을 통과할 수 없다.
_STATE_PURPOSE = "kakao_oauth_state"


def new_state() -> str:
    """추측할 수 없는 임의 값. `.`이 들어가지 않는 URL-safe 문자열이라 토큰 구분자와 안 섞인다."""
    return secrets.token_urlsafe(32)


def _sign_state(state: str, issued_at: int, secret: str, guest_user_id: str | None = None) -> str:
    # 게스트 id도 서명 대상이다 — 값을 빼거나 바꾸면 서명이 어긋난다(#560).
    guest_part = f".{guest_user_id}" if guest_user_id else ""
    return _sign(f"{_STATE_PURPOSE}:{state}.{issued_at}{guest_part}", secret)


def create_state_cookie_value(state: str, *, secret: str, issued_at: int, guest_user_id: str | None = None) -> str:
    """`state.발급시각.서명` — 로그인 시작 때 HttpOnly 쿠키에 넣는다. 게스트가 시작했으면
    `state.발급시각.게스트id.서명`(#560) — 콜백이 어느 게스트 기록을 합칠지 서버가 서명해 들고 간다."""
    if guest_user_id is not None and (not guest_user_id or "." in guest_user_id):
        raise ValueError("guest_user_id는 비어 있거나 '.'를 포함할 수 없다")
    signature = _sign_state(state, issued_at, secret, guest_user_id)
    if guest_user_id:
        return f"{state}.{issued_at}.{guest_user_id}.{signature}"
    return f"{state}.{issued_at}.{signature}"


class StateClaims(NamedTuple):
    guest_user_id: str | None


def parse_state(cookie_value: str | None, state_param: str | None, *, secret: str, now: int,
                ttl_seconds: int = STATE_TTL_SECONDS) -> StateClaims | None:
    """콜백의 `state` 쿼리가 이 브라우저가 시작한 로그인의 값인지 확인하고, 쿠키에 실린 게스트 id를 꺼낸다.
    둘 중 하나가 없거나, 쿠키 서명이 틀리거나 만료됐거나, 두 값이 다르면 None. 어느 경우인지는 구분해 알리지
    않는다(parse_session_token과 같은 이유 — 위조 시도에 오라클을 주지 않는다)."""
    if not cookie_value or not state_param:
        return None
    parts = cookie_value.split(".")
    if len(parts) == 3:
        state, issued_at_raw, signature = parts
        guest_user_id = None
    elif len(parts) == 4:
        state, issued_at_raw, guest_user_id, signature = parts
        if not guest_user_id:
            return None
    else:
        return None
    if not state or not issued_at_raw.isdigit():
        return None
    issued_at = int(issued_at_raw)
    if not hmac.compare_digest(_sign_state(state, issued_at, secret, guest_user_id), signature):
        return None
    if now < issued_at or now - issued_at > ttl_seconds:
        return None
    if not hmac.compare_digest(state.encode("utf-8"), state_param.encode("utf-8")):
        return None
    return StateClaims(guest_user_id)


def verify_state(cookie_value: str | None, state_param: str | None, *, secret: str, now: int,
                 ttl_seconds: int = STATE_TTL_SECONDS) -> bool:
    return parse_state(cookie_value, state_param, secret=secret, now=now, ttl_seconds=ttl_seconds) is not None


def kakao_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return f"{KAKAO_AUTHORIZE_URL}?{query}"


def state_cookie_path(redirect_uri: str) -> str:
    """state 쿠키를 콜백에만 싣는 경로. 배포는 앞단이 /api를 벗겨 넘기므로(#819) 서버 안 경로가 아니라
    브라우저가 보는 콜백 주소의 부모 경로를 쓴다."""
    return urlsplit(redirect_uri).path.rsplit("/", 1)[0] or "/"


# ---- 탈퇴 계정 복구 기간과 선택 대기 쿠키(#855, #857) ----
WITHDRAWN_DISPLAY_NAME = "탈퇴한 구성원"   # 탈퇴한 사람의 표시 이름. 정리된 계정의 users 행에도 이 값이 남는다
ACCOUNT_RESTORE_DAYS = 7
PENDING_TTL_SECONDS = 60 * 10   # 콜백 → 선택 화면 → 제출까지. state 쿠키와 같이 짧게 둔다.
_PENDING_PURPOSE = "pending_account"
_SECONDS_PER_DAY = 60 * 60 * 24


def restore_deadline(deleted_at: datetime) -> datetime:
    """이 시각까지 되살릴 수 있다(탈퇴 + 7일). 콜백·GET·POST·정리 작업이 모두 이 한 곳으로 판정한다."""
    return deleted_at + timedelta(days=ACCOUNT_RESTORE_DAYS)


def is_restorable(deleted_at: datetime, now: datetime) -> bool:
    return now < restore_deadline(deleted_at)


def restore_days_left(deleted_at: datetime, now: datetime) -> int:
    """남은 날수(올림). 기한이 지났으면 0."""
    remaining = (restore_deadline(deleted_at) - now).total_seconds()
    return max(0, math.ceil(remaining / _SECONDS_PER_DAY))


def deleted_at_stamp(deleted_at: datetime) -> int:
    """탈퇴 시각을 쿠키에 묶는 값 — 마이크로초까지(같은 사용자의 다음 탈퇴 회차와 구분한다)."""
    return int(deleted_at.timestamp() * 1_000_000)


class PendingClaims(NamedTuple):
    user_id: str
    provider: str
    deleted_stamp: int


def _sign_pending(user_id: str, provider: str, deleted_stamp: int, issued_at: int, secret: str) -> str:
    # 용도·사용자·로그인 수단·탈퇴 시각이 모두 서명 대상이다 — 하나라도 바꾸면 어긋난다.
    return _sign(f"{_PENDING_PURPOSE}:{user_id}.{provider}.{deleted_stamp}.{issued_at}", secret)


def create_pending_cookie_value(user_id: str, provider: str, deleted_at: datetime, *, secret: str, issued_at: int) -> str:
    """`사용자id.수단.탈퇴시각.발급시각.서명` — 콜백이 탈퇴 계정을 만났을 때 한 번의 선택에만 쓰는 쿠키 값."""
    if not user_id or "." in user_id or not provider or "." in provider:
        raise ValueError("user_id·provider는 비어 있거나 '.'를 포함할 수 없다")
    stamp = deleted_at_stamp(deleted_at)
    return f"{user_id}.{provider}.{stamp}.{issued_at}.{_sign_pending(user_id, provider, stamp, issued_at, secret)}"


def parse_pending_cookie(cookie_value: str | None, *, secret: str, now: int, ttl_seconds: int = PENDING_TTL_SECONDS) -> PendingClaims | None:
    """서명·형식·만료를 확인해 (사용자, 수단, 탈퇴 시각)을 돌려준다. 어느 경우인지는 구분해 알리지 않는다.
    서버가 현재 상태와 맞는지는 호출부가 따로 대조한다(복구·정리·다음 탈퇴 회차 거절)."""
    if not cookie_value:
        return None
    parts = cookie_value.split(".")
    if len(parts) != 5:
        return None
    user_id, provider, stamp_raw, issued_at_raw, signature = parts
    if not user_id or not provider or not stamp_raw.isdigit() or not issued_at_raw.isdigit():
        return None
    stamp, issued_at = int(stamp_raw), int(issued_at_raw)
    if not hmac.compare_digest(_sign_pending(user_id, provider, stamp, issued_at, secret), signature):
        return None
    if now < issued_at or now - issued_at > ttl_seconds:
        return None
    return PendingClaims(user_id, provider, stamp)


def pending_cookie_path(redirect_uri: str) -> str:
    """선택 대기 쿠키를 `/auth/pending`에 싣는 경로 — state 쿠키 경로(`.../auth/kakao`)의 부모(`.../auth`).
    같은 규칙으로 브라우저가 보는 주소에서 구하므로 앞단이 /api를 벗겨도 맞는다(#819)."""
    return state_cookie_path(redirect_uri).rsplit("/", 1)[0] or "/"


def is_revoked(issued_at: int, sessions_valid_after: datetime | None) -> bool:
    """로그아웃이 기록한 sessions_valid_after 이전(같은 초 포함)에 발급된 토큰이면 True.
    토큰 발급 시각은 초 단위라, 로그아웃과 같은 초에 복사된 토큰도 막으려고 `<=`로 비교한다 —
    대가로 로그아웃 직후 1초 안의 재로그인 토큰도 거절되지만 카카오 왕복이 있어 사실상 없다."""
    if sessions_valid_after is None:
        return False
    return issued_at <= int(sessions_valid_after.timestamp())


def display_name_from_kakao_profile(profile: dict) -> str:
    """카카오 `GET /v2/user/me` 응답(https://kapi.kakao.com)에서 표시 이름을 뽑는다.
    닉네임 동의를 안 받았거나 비어있으면 카카오 회원번호로 대체한다 — 빈 문자열을 users.display_name에
    그대로 저장하지 않는다(display_name은 NOT NULL, 화면에 빈 이름표가 뜨는 것도 피한다)."""
    kakao_account = profile.get("kakao_account") or {}
    profile_obj = kakao_account.get("profile") or {}
    nickname = profile_obj.get("nickname")
    if nickname:
        return nickname
    return f"user_{profile['id']}"


GUEST_LIMIT_PER_INVITE = 10   # 초대 토큰 하나로 만들 수 있는 게스트 수(#472)
LAST_SEEN_REFRESH_SECONDS = 60 * 60 * 24   # last_seen_at은 하루 한 번만 갱신한다


def should_refresh_last_seen(last_seen_at: datetime | None, now: datetime) -> bool:
    return last_seen_at is None or (now - last_seen_at).total_seconds() >= LAST_SEEN_REFRESH_SECONDS

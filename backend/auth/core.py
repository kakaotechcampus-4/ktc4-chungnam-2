"""
순수 함수만 — I/O 없음(docs/code-quality.md 기능형 코어). 세션 토큰 서명/검증과 카카오 프로필
파싱은 전부 입력을 받아 값을 반환할 뿐이라 여기 둔다. DB·HTTP 호출은 auth/service.py(셸)로.
"""

import hashlib
import hmac

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30일. 세션 테이블이 없어(data-model.md) 무상태 토큰의 자체 만료로 대신한다.


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(user_id: str, *, secret: str, issued_at: int) -> str:
    """`user_id.발급시각.서명` 형태의 무상태 서명 토큰. httpOnly 쿠키 값으로 그대로 들어간다
    (최종기획안 13절 "토큰을 프론트에 두지 않는다" — 값 자체는 프론트 JS가 못 읽지만, 세션을
    DB에 두지 않기로 한 결정과는 별개 사안이다)."""
    payload = f"{user_id}.{issued_at}"
    return f"{payload}.{_sign(payload, secret)}"


def parse_session_token(token: str, *, secret: str, now: int, ttl_seconds: int = SESSION_TTL_SECONDS) -> str | None:
    """서명·형식·만료를 확인해 user_id를 돌려준다. 뭐가 문제든 조용히 None만 반환한다 —
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
    return user_id


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

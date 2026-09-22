"""auth/core.py 순수 함수 테스트 — I/O 없이 직접 호출한다(docs/code-quality.md)."""

from auth.core import create_session_token, display_name_from_kakao_profile, parse_session_token

SECRET = "test-secret"


def test_round_trip_returns_the_same_user_id():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    assert parse_session_token(token, secret=SECRET, now=1_000) == "user_1"


def test_expired_token_is_rejected():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    just_after_ttl = 1_000 + 60 * 60 * 24 * 30 + 1
    assert parse_session_token(token, secret=SECRET, now=just_after_ttl) is None


def test_token_at_exact_ttl_boundary_is_still_valid():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    at_ttl = 1_000 + 60 * 60 * 24 * 30
    assert parse_session_token(token, secret=SECRET, now=at_ttl) == "user_1"


def test_tampered_user_id_is_rejected():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    _, issued_at, signature = token.split(".")
    forged = f"user_2.{issued_at}.{signature}"
    assert parse_session_token(forged, secret=SECRET, now=1_000) is None


def test_wrong_secret_is_rejected():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    assert parse_session_token(token, secret="other-secret", now=1_000) is None


def test_malformed_token_is_rejected():
    assert parse_session_token("not-a-token", secret=SECRET, now=1_000) is None
    assert parse_session_token("a.b.c.d", secret=SECRET, now=1_000) is None
    assert parse_session_token("user_1.not-a-number.sig", secret=SECRET, now=1_000) is None


def test_future_issued_at_is_rejected():
    """시계가 서버보다 앞선 위조 토큰(issued_at > now)을 만료 계산이 음수가 돼 통과시키지 않는지."""
    token = create_session_token("user_1", secret=SECRET, issued_at=2_000)
    assert parse_session_token(token, secret=SECRET, now=1_000) is None


def test_display_name_from_kakao_profile_prefers_nickname():
    profile = {"id": 42, "kakao_account": {"profile": {"nickname": "철수"}}}
    assert display_name_from_kakao_profile(profile) == "철수"


def test_display_name_from_kakao_profile_falls_back_to_user_id_without_nickname():
    profile = {"id": 42, "kakao_account": {"profile": {}}}
    assert display_name_from_kakao_profile(profile) == "user_42"


def test_display_name_from_kakao_profile_falls_back_without_kakao_account():
    profile = {"id": 42}
    assert display_name_from_kakao_profile(profile) == "user_42"

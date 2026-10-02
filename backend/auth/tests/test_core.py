"""auth/core.py 순수 함수 테스트 — I/O 없이 직접 호출한다(docs/code-quality.md)."""

from datetime import datetime, timezone

from auth import core
from auth.core import create_session_token, is_revoked, display_name_from_kakao_profile, parse_session_token

SECRET = "test-secret"


def test_round_trip_returns_the_same_user_id():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    assert parse_session_token(token, secret=SECRET, now=1_000) == ("user_1", 1_000)


def test_expired_token_is_rejected():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    just_after_ttl = 1_000 + 60 * 60 * 24 * 30 + 1
    assert parse_session_token(token, secret=SECRET, now=just_after_ttl) is None


def test_token_at_exact_ttl_boundary_is_still_valid():
    token = create_session_token("user_1", secret=SECRET, issued_at=1_000)
    at_ttl = 1_000 + 60 * 60 * 24 * 30
    assert parse_session_token(token, secret=SECRET, now=at_ttl) == ("user_1", 1_000)


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


def test_is_revoked_without_logout_record_is_false():
    assert is_revoked(1_000, None) is False


def test_is_revoked_token_issued_before_or_in_same_second_as_logout():
    logout = datetime.fromtimestamp(1_000.5, tz=timezone.utc)
    assert is_revoked(999, logout) is True
    assert is_revoked(1_000, logout) is True


def test_is_revoked_token_issued_after_logout_is_valid():
    logout = datetime.fromtimestamp(1_000.5, tz=timezone.utc)
    assert is_revoked(1_001, logout) is False


# ---- OAuth state (#128) ----

def _state_cookie(state="s-1", issued_at=1_000, secret=SECRET):
    return core.create_state_cookie_value(state, secret=secret, issued_at=issued_at)


def test_state_round_trip_is_accepted():
    assert core.verify_state(_state_cookie(), "s-1", secret=SECRET, now=1_000)


def test_state_is_rejected_when_either_side_is_missing():
    assert not core.verify_state(None, "s-1", secret=SECRET, now=1_000)
    assert not core.verify_state(_state_cookie(), None, secret=SECRET, now=1_000)
    assert not core.verify_state("", "", secret=SECRET, now=1_000)


def test_state_is_rejected_when_param_differs_from_cookie():
    assert not core.verify_state(_state_cookie("s-1"), "s-2", secret=SECRET, now=1_000)


def test_state_is_rejected_when_signature_is_wrong():
    assert not core.verify_state(_state_cookie(secret="other"), "s-1", secret=SECRET, now=1_000)
    assert not core.verify_state("s-1.1000.deadbeef", "s-1", secret=SECRET, now=1_000)
    assert not core.verify_state("not-a-token", "s-1", secret=SECRET, now=1_000)


def test_state_expires_after_ttl_but_not_at_the_boundary():
    cookie = _state_cookie(issued_at=1_000)
    assert core.verify_state(cookie, "s-1", secret=SECRET, now=1_000 + core.STATE_TTL_SECONDS)
    assert not core.verify_state(cookie, "s-1", secret=SECRET, now=1_000 + core.STATE_TTL_SECONDS + 1)
    assert not core.verify_state(cookie, "s-1", secret=SECRET, now=999)   # 미래에 발급된 값


def test_state_cookie_and_session_token_cannot_stand_in_for_each_other():
    session = create_session_token("s-1", secret=SECRET, issued_at=1_000)
    assert not core.verify_state(session, "s-1", secret=SECRET, now=1_000)
    assert parse_session_token(_state_cookie("s-1"), secret=SECRET, now=1_000) is None


def test_new_state_is_random_and_has_no_token_separator():
    values = {core.new_state() for _ in range(50)}
    assert len(values) == 50
    assert all("." not in v and len(v) >= 32 for v in values)


def test_kakao_authorize_url_encodes_parameters():
    url = core.kakao_authorize_url(client_id="cid", redirect_uri="http://localhost:8000/auth/kakao/callback", state="st")
    assert url == (
        "https://kauth.kakao.com/oauth/authorize?response_type=code&client_id=cid"
        "&redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fauth%2Fkakao%2Fcallback&state=st"
    )

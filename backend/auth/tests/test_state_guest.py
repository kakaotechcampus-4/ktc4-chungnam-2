"""게스트 id를 실은 OAuth state 쿠키 순수 함수 테스트(#560) — I/O 없이 직접 호출한다."""

import pytest

from auth import core

SECRET = "test-secret"


def _plain_cookie(state="s-1", issued_at=1_000, secret=SECRET):
    return core.create_state_cookie_value(state, secret=secret, issued_at=issued_at)


def _guest_cookie(guest="g1", state="s-1", issued_at=1_000, secret=SECRET):
    return core.create_state_cookie_value(state, secret=secret, issued_at=issued_at, guest_user_id=guest)


def test_state_without_guest_has_no_guest_user_id():
    assert core.parse_state(_plain_cookie(), "s-1", secret=SECRET, now=1_000) == core.StateClaims(None)


def test_state_carries_the_guest_user_id():
    assert core.parse_state(_guest_cookie("g1"), "s-1", secret=SECRET, now=1_000) == core.StateClaims("g1")
    assert core.verify_state(_guest_cookie("g1"), "s-1", secret=SECRET, now=1_000)


def test_swapped_guest_id_is_rejected():
    _, issued_at, _, signature = _guest_cookie("g1").split(".")
    assert core.parse_state(f"s-1.{issued_at}.victim.{signature}", "s-1", secret=SECRET, now=1_000) is None


def test_stripped_or_added_guest_id_is_rejected():
    state, issued_at, _, signature = _guest_cookie("g1").split(".")
    assert core.parse_state(f"{state}.{issued_at}.{signature}", "s-1", secret=SECRET, now=1_000) is None   # 게스트 id를 뗐다
    p_state, p_issued_at, p_signature = _plain_cookie().split(".")
    assert core.parse_state(f"{p_state}.{p_issued_at}.g1.{p_signature}", "s-1", secret=SECRET, now=1_000) is None   # 서명 없이 붙였다


def test_wrong_secret_and_empty_guest_id_are_rejected():
    assert core.parse_state(_guest_cookie(secret="other"), "s-1", secret=SECRET, now=1_000) is None
    state, issued_at, _, signature = _guest_cookie("g1").split(".")
    assert core.parse_state(f"{state}.{issued_at}..{signature}", "s-1", secret=SECRET, now=1_000) is None


def test_guest_state_expires_and_must_match_the_param():
    cookie = _guest_cookie()
    assert core.parse_state(cookie, "s-1", secret=SECRET, now=1_000 + core.STATE_TTL_SECONDS) is not None
    assert core.parse_state(cookie, "s-1", secret=SECRET, now=1_000 + core.STATE_TTL_SECONDS + 1) is None
    assert core.parse_state(cookie, "s-2", secret=SECRET, now=1_000) is None


@pytest.mark.parametrize("bad", ["", "a.b"])
def test_guest_user_id_that_breaks_the_token_format_cannot_be_signed(bad):
    with pytest.raises(ValueError):
        core.create_state_cookie_value("s-1", secret=SECRET, issued_at=1_000, guest_user_id=bad)

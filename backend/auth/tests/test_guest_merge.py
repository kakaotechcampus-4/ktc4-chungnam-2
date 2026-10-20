"""게스트 → 카카오 전환 시 기록 합치기 통합 테스트(#560) — 실제 PostgreSQL 필요(conftest.py 참고), main.app을 그대로 태운다.

각 모듈의 `reassign_user`는 아직 없는 것도 있어 대역(MERGE_STEPS 교체)으로 검증한다. 카카오 HTTP만 몬키패치한다.
"""

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from auth import core, service
from auth.models import User
from auth.testing import session_cookie
from auth.tests.test_router import (  # noqa: F401 — kakao_configured는 픽스처
    _callback, _has_session_cookie, _is_cleared, _login_error, _mock_kakao_login, _seed_user, _start_login,
    kakao_configured, LOGIN_URL,
)
from auth.tests.test_service import _FakeResponse
from common.settings import settings

STEP_NAMES = ["maps", "pins", "recommend", "shortlist", "notifications", "feedback"]


def _seed_guest(db_session, user_id="g1", display_name="손님"):
    row = User(id=user_id, provider="guest", provider_user_id=f"pg_{user_id}", display_name=display_name, is_guest=True)
    db_session.add(row)
    db_session.flush()
    return row


def _recording_steps(monkeypatch, *, fail_at=None, on_step=None):
    """모듈 api 대역 — 부른 순서와 인자를 기록한다. fail_at 단계는 예외를 던진다."""
    calls = []

    def make(name):
        def reassign_user(db, *, from_user_id, to_user_id):
            calls.append((name, from_user_id, to_user_id))
            if on_step:
                on_step(name, db, from_user_id)
            if name == fail_at:
                raise RuntimeError("secret detail that must not be logged")
        return SimpleNamespace(reassign_user=reassign_user)

    monkeypatch.setattr(service, "MERGE_STEPS", tuple((n, make(n)) for n in STEP_NAMES))
    return calls


def _state_cookie_value(client) -> str:
    return next(c.value for c in client.cookies.jar if c.name == "kakao_oauth_state")


def _start_login_as(client, user_id) -> str:
    """세션 쿠키를 들고 로그인 시작 — 카카오로 보낸 state를 돌려준다."""
    resp = client.get("/auth/kakao/login", cookies=session_cookie(user_id), follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _guest_merged(resp) -> str | None:
    return parse_qs(urlparse(resp.headers["location"]).query).get("guest_merged", [None])[0]


def _callback_with_signed_state(client, cookie_value):
    """서버가 시작한 적 없는 조합의 state 쿠키로 콜백을 호출한다(쿠키의 state 값은 "st")."""
    client.cookies.clear()
    client.cookies.set("kakao_oauth_state", cookie_value, path="/auth/kakao")
    return _callback(client, code="auth-code", state="st")


def _signed_state(guest_user_id) -> str:
    return core.create_state_cookie_value(
        "st", secret=settings.session_secret, issued_at=int(time.time()), guest_user_id=guest_user_id,
    )


# ---- 로그인 시작: state 쿠키에 게스트 id ----

def test_login_from_a_guest_session_puts_the_guest_id_in_the_state_cookie(app_client, db_session, kakao_configured):
    _seed_guest(db_session, "g1")
    state = _start_login_as(app_client, "g1")
    claims = core.parse_state(_state_cookie_value(app_client), state, secret=settings.session_secret, now=int(time.time()))
    assert claims == core.StateClaims("g1")


@pytest.mark.parametrize("session", ["none", "kakao_user", "garbage", "unknown_user", "withdrawn_guest", "logged_out_guest"])
def test_login_without_a_live_guest_session_carries_no_guest_id(app_client, db_session, kakao_configured, session):
    _seed_user(db_session, user_id="k1")
    _seed_guest(db_session, "gw").deleted_at = datetime.now(timezone.utc)
    _seed_guest(db_session, "go").sessions_valid_after = datetime.now(timezone.utc)
    db_session.flush()
    cookies = {
        "none": {}, "kakao_user": session_cookie("k1"), "garbage": {"session": "x.y.z"},
        "unknown_user": session_cookie("nobody"), "withdrawn_guest": session_cookie("gw"),
        "logged_out_guest": session_cookie("go"),
    }[session]
    resp = app_client.get("/auth/kakao/login", cookies=cookies, follow_redirects=False)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    claims = core.parse_state(_state_cookie_value(app_client), state, secret=settings.session_secret, now=int(time.time()))
    assert claims == core.StateClaims(None)


# ---- 콜백: 합치기 ----

def test_guest_login_merges_records_and_reports_guest_merged_true(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch, kakao_id=7, nickname="민수")
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    state = _start_login_as(app_client, "g1")

    resp = _callback(app_client, code="auth-code", state=state)

    kakao_user = db_session.execute(select(User).where(User.provider == "kakao")).scalar_one()
    assert _guest_merged(resp) == "true"
    assert _login_error(resp) is None
    assert [c[0] for c in calls] == STEP_NAMES
    assert all(c[1:] == ("g1", kakao_user.id) for c in calls)
    assert db_session.get(User, "g1").deleted_at is not None
    assert _has_session_cookie(resp) and _is_cleared(resp, "kakao_oauth_state")
    me = app_client.get("/auth/me")   # 응답의 세션 쿠키가 카카오 계정이다
    assert me.status_code == 200 and me.json()["id"] == kakao_user.id and me.json()["is_guest"] is False


def test_failed_merge_keeps_guest_and_rolls_back_but_login_succeeds(app_client, db_session, monkeypatch, kakao_configured, caplog):
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "g1", display_name="손님")

    def touch_guest(name, db, from_user_id):
        if name == "maps":   # 앞 단계의 쓰기 — 뒤 단계 실패로 같이 되돌아가야 한다
            db.get(User, from_user_id).display_name = "옮기다 만 이름"
            db.flush()

    _recording_steps(monkeypatch, fail_at="recommend", on_step=touch_guest)
    state = _start_login_as(app_client, "g1")

    with caplog.at_level("ERROR"):
        resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "false"
    assert _login_error(resp) is None
    assert _has_session_cookie(resp)   # 카카오 로그인은 성공이다
    assert db_session.execute(select(User).where(User.provider == "kakao")).scalar_one() is not None
    guest = db_session.get(User, "g1")
    assert guest.deleted_at is None and guest.display_name == "손님"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "step=recommend" in logged and "RuntimeError" in logged
    assert "secret detail" not in logged


def test_module_without_reassign_user_fails_the_merge_instead_of_deleting_the_guest(app_client, db_session, monkeypatch, kakao_configured):
    """아직 reassign_user가 없는 모듈이 있으면 일부만 옮긴 채 게스트를 지우지 않는다."""
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "g1")
    monkeypatch.setattr(service, "MERGE_STEPS", (("maps", SimpleNamespace()),))
    state = _start_login_as(app_client, "g1")

    resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "false"
    assert db_session.get(User, "g1").deleted_at is None


def test_non_guest_login_has_no_guest_merged_query(app_client, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    calls = _recording_steps(monkeypatch)
    resp = _callback(app_client, code="auth-code", state=_start_login(app_client))
    assert _guest_merged(resp) is None and _login_error(resp) is None
    assert resp.headers["location"] == LOGIN_URL
    assert calls == []


def test_login_started_by_a_kakao_user_does_not_merge(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    _seed_user(db_session, user_id="k1")
    calls = _recording_steps(monkeypatch)
    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "k1"))
    assert _guest_merged(resp) is None and calls == []


@pytest.mark.parametrize("target", ["already_merged", "not_a_guest", "unknown"])
def test_state_naming_a_dead_or_non_guest_account_merges_nothing(app_client, db_session, monkeypatch, kakao_configured, target):
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "gm").deleted_at = datetime.now(timezone.utc)   # 이미 합쳐진 게스트
    _seed_user(db_session, user_id="plain")
    calls = _recording_steps(monkeypatch)
    guest_id = {"already_merged": "gm", "not_a_guest": "plain", "unknown": "nobody"}[target]

    resp = _callback_with_signed_state(app_client, _signed_state(guest_id))

    assert _guest_merged(resp) is None and _login_error(resp) is None
    assert calls == []
    assert db_session.get(User, "plain").deleted_at is None
    assert _has_session_cookie(resp)


def test_guest_cannot_be_merged_into_itself(db_session, monkeypatch):
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="g1") is None
    assert calls == [] and db_session.get(User, "g1").deleted_at is None


def test_same_guest_is_merged_only_once(db_session, monkeypatch):
    _seed_user(db_session, user_id="k1")
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="k1") is True
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="k1") is None
    assert len(calls) == len(STEP_NAMES)


def test_forged_guest_id_in_state_cookie_is_invalid_state_and_merges_nothing(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "victim")
    calls = _recording_steps(monkeypatch)
    _start_login(app_client)   # 게스트 아닌 시작
    state, issued_at, signature = _state_cookie_value(app_client).split(".")
    app_client.cookies.clear()   # 진짜 쿠키가 같이 실리지 않게 비운다
    app_client.cookies.set("kakao_oauth_state", f"{state}.{issued_at}.victim.{signature}", path="/auth/kakao")   # 서명 없이 게스트 id를 붙임

    resp = _callback(app_client, code="auth-code", state=state)

    assert _login_error(resp) == "invalid_state" and calls == []
    assert db_session.get(User, "victim").deleted_at is None


def test_guest_merged_replaces_same_named_query_and_keeps_the_rest_of_entry_url(app_client, db_session, monkeypatch, kakao_configured):
    import dataclasses

    import auth.router as router_module

    entry = "http://localhost:5173/login?next=%2Fm%2F1&guest_merged=stale#top"
    monkeypatch.setattr(router_module, "settings", dataclasses.replace(router_module.settings, frontend_login_redirect_url=entry))
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "g1")
    _recording_steps(monkeypatch)

    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "g1"))

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query) == {"next": ["/m/1"], "guest_merged": ["true"]}
    assert location.fragment == "top"


def test_kakao_failure_for_a_guest_login_keeps_the_guest_and_adds_no_merge_query(app_client, db_session, monkeypatch, kakao_configured):
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(400, {}))

    resp = _callback(app_client, code="bad", state=_start_login_as(app_client, "g1"))

    assert _login_error(resp) == "kakao_failed" and _guest_merged(resp) is None
    assert calls == [] and db_session.get(User, "g1").deleted_at is None

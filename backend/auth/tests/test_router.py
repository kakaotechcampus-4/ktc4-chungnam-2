"""auth/router.py 통합 테스트 — 실제 PostgreSQL 필요(conftest.py 참고), main.app을 그대로 태운다.

인증은 서명된 세션 토큰이다(#126) — `auth.testing.session_cookie`로 만든다. 카카오 콜백은 실제
service.login_with_kakao_code를 타므로 그 안의 httpx 호출만 몬키패치한다.
"""

import dataclasses
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth import service
from auth.models import User
from auth.testing import session_cookie
from auth.tests.test_service import _FakeResponse


LOGIN_URL = "http://localhost:5173/login"


def _seed_user(db_session, *, user_id="user_1", display_name="철수"):
    row = User(id=user_id, provider="kakao", provider_user_id=f"kakao_{user_id}", display_name=display_name)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def kakao_configured(monkeypatch):
    """로그인 시작에 필요한 카카오 설정 — 로컬 .env에 값이 있든 없든 테스트는 같은 값으로 돈다."""
    import auth.router as router_module

    configured = dataclasses.replace(
        router_module.settings,
        kakao_client_id="test-client-id",
        kakao_redirect_uri="http://localhost:8000/auth/kakao/callback",
        frontend_login_redirect_url=LOGIN_URL,
    )
    monkeypatch.setattr(router_module, "settings", configured)


def _mock_kakao_login(monkeypatch, *, kakao_id=7, nickname="민수"):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"access_token": "fake-token"}))
    monkeypatch.setattr(
        service.httpx, "get",
        lambda url, **kw: _FakeResponse(200, {"id": kakao_id, "kakao_account": {"profile": {"nickname": nickname}}}),
    )


def _start_login(client) -> str:
    """로그인 시작 — 카카오로 보낸 state를 돌려준다. 이 client의 쿠키 항아리에 state 쿠키가 남는다."""
    resp = client.get("/auth/kakao/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _other_browser(app_client):
    return TestClient(app_client.app)   # with 없이 — lifespan은 app_client가 이미 열었다


def _is_cleared(resp, cookie_name: str) -> bool:
    return any(
        h.startswith(f"{cookie_name}=") and "Max-Age=0" in h
        for h in resp.headers.get_list("set-cookie")
    )


# ---- GET /auth/kakao/login (#128) ----

def test_kakao_login_redirects_to_kakao_with_state_and_sets_signed_state_cookie(app_client, kakao_configured):
    resp = app_client.get("/auth/kakao/login", follow_redirects=False)

    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://kauth.kakao.com/oauth/authorize"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/kakao/callback"]
    assert len(query["state"][0]) >= 32

    set_cookie = resp.headers["set-cookie"].lower()
    assert "kakao_oauth_state=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=600" in set_cookie


def test_kakao_login_uses_a_fresh_state_each_time(app_client, kakao_configured):
    assert _start_login(app_client) != _start_login(_other_browser(app_client))


def test_kakao_login_without_kakao_settings_fails_loudly(app_client, monkeypatch):
    import auth.router as router_module

    monkeypatch.setattr(router_module, "settings", dataclasses.replace(router_module.settings, kakao_client_id=""))
    resp = app_client.get("/auth/kakao/login", follow_redirects=False)
    assert resp.status_code == 500
    assert "kakao_oauth_state" not in resp.headers.get("set-cookie", "")


def test_kakao_login_needs_no_session(app_client, kakao_configured):
    """로그인 전 경로라 쿠키 없이 호출된다 — 전역 인증이 붙으면 아무도 로그인을 시작할 수 없다."""
    assert app_client.get("/auth/kakao/login", follow_redirects=False).status_code == 302


def _login_error(resp) -> str | None:
    """실패 302가 진입점에 붙인 login_error 값. 성공이면 None."""
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query).get("login_error", [None])[0]


def _has_session_cookie(resp) -> bool:
    return any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))


def _callback(client, **params):
    return client.get("/auth/kakao/callback", params=params, follow_redirects=False)


def _assert_failed_with(resp, reason, db_session=None):
    assert _login_error(resp) == reason
    assert not _has_session_cookie(resp)
    assert _is_cleared(resp, "kakao_oauth_state")
    if db_session is not None:
        assert db_session.execute(select(User)).first() is None   # 사용자도 만들어지지 않았다


# ---- GET /auth/kakao/callback ----

def test_kakao_callback_creates_user_and_sets_session_cookie(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)

    resp = app_client.get("/auth/kakao/callback", params={"code": "auth-code", "state": state}, follow_redirects=False)

    assert resp.status_code == 302
    assert "session" in resp.cookies

    row = db_session.execute(select(User).where(User.provider_user_id == "7")).scalar_one()
    assert row.display_name == "민수"


def test_success_redirects_to_entry_without_login_error_and_clears_state_cookie(app_client, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)

    resp = _callback(app_client, code="auth-code", state=state)

    assert _login_error(resp) is None
    assert resp.headers["location"] == LOGIN_URL
    assert _has_session_cookie(resp)
    assert _is_cleared(resp, "kakao_oauth_state")


def test_user_cancel_at_kakao_is_cancelled(app_client, db_session, monkeypatch, kakao_configured):
    """카카오 화면에서 취소하면 code 없이 error(와 state)만 돌아온다 — 예전엔 422 JSON이 그대로 보였다."""
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)

    resp = _callback(app_client, error="access_denied", error_description="User denied access", state=state)

    _assert_failed_with(resp, "cancelled", db_session)


def test_missing_code_without_error_is_also_cancelled(app_client, kakao_configured):
    state = _start_login(app_client)
    _assert_failed_with(_callback(app_client, state=state), "cancelled")


def test_error_with_code_does_not_log_in(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)
    _assert_failed_with(_callback(app_client, code="auth-code", error="access_denied", state=state), "cancelled", db_session)


def test_cancel_with_bad_state_is_invalid_state_not_cancelled(app_client, kakao_configured):
    """state 검증이 먼저다 — 위조된 요청이 error만 붙여 cancelled로 위장하지 못한다."""
    _start_login(app_client)
    _assert_failed_with(_callback(app_client, error="access_denied", state="forged"), "invalid_state")


def test_no_kakao_call_is_made_when_state_is_invalid(app_client, monkeypatch, kakao_configured):
    def boom(*a, **k):
        raise AssertionError("state가 틀렸는데 카카오를 불렀다")

    monkeypatch.setattr(service.httpx, "post", boom)
    monkeypatch.setattr(service.httpx, "get", boom)
    _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="x", state="forged"), "invalid_state")


def test_token_exchange_failure_is_kakao_failed(app_client, db_session, monkeypatch, kakao_configured):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(400, {"error": "invalid_grant"}))
    state = _start_login(app_client)

    resp = _callback(app_client, code="bad-code", state=state)

    _assert_failed_with(resp, "kakao_failed", db_session)
    assert "bad-code" not in resp.headers["location"]


def test_token_response_without_access_token_is_kakao_failed_not_500(app_client, db_session, monkeypatch, kakao_configured):
    """멘토 지적: access_token이 없으면 KeyError로 500이 되던 경로."""
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"token_type": "bearer"}))
    state = _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="auth-code", state=state), "kakao_failed", db_session)


def test_profile_failure_is_kakao_failed(app_client, db_session, monkeypatch, kakao_configured):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"access_token": "fake-token"}))
    monkeypatch.setattr(service.httpx, "get", lambda url, **kw: _FakeResponse(401, {"error": "invalid_token"}))
    state = _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="auth-code", state=state), "kakao_failed", db_session)


def test_kakao_network_error_is_kakao_failed(app_client, monkeypatch, kakao_configured):
    import httpx

    def timeout(url, **kw):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(service.httpx, "post", timeout)
    state = _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="auth-code", state=state), "kakao_failed")


def test_unexpected_exception_is_server_error_and_logs_only_the_kind(app_client, monkeypatch, caplog, kakao_configured):
    def broken(db, *, code):
        raise RuntimeError("secret-token-abc leaked in message")

    monkeypatch.setattr(service, "login_with_kakao_code", broken)
    state = _start_login(app_client)

    with caplog.at_level("DEBUG"):
        resp = _callback(app_client, code="auth-code", state=state)

    _assert_failed_with(resp, "server_error")
    assert "RuntimeError" in caplog.text
    assert "secret-token-abc" not in caplog.text


def test_kakao_failure_logs_do_not_contain_response_body_or_token(app_client, monkeypatch, caplog, kakao_configured):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"access_token": "tok-123", "extra": "body-secret"}))
    monkeypatch.setattr(service.httpx, "get", lambda url, **kw: _FakeResponse(500, {"error": "body-secret"}))
    state = _start_login(app_client)

    with caplog.at_level("DEBUG"):
        _assert_failed_with(_callback(app_client, code="auth-code", state=state), "kakao_failed")

    assert "tok-123" not in caplog.text and "body-secret" not in caplog.text
    assert "kakao_status=500" in caplog.text


def test_failure_keeps_existing_query_of_the_entry_url(app_client, monkeypatch, kakao_configured):
    import auth.router as router_module

    monkeypatch.setattr(
        router_module, "settings",
        dataclasses.replace(router_module.settings, frontend_login_redirect_url=f"{LOGIN_URL}?next=%2Fmaps%2F1&login_error=old#top"),
    )
    state = _start_login(app_client)

    resp = _callback(app_client, error="access_denied", state=state)

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query) == {"next": ["/maps/1"], "login_error": ["cancelled"]}   # 기존 쿼리 보존, 옛 login_error는 대체
    assert location.fragment == "top"
    assert f"{location.scheme}://{location.netloc}{location.path}" == LOGIN_URL


def test_success_keeps_entry_url_untouched(app_client, monkeypatch, kakao_configured):
    import auth.router as router_module

    entry = f"{LOGIN_URL}?next=%2Fmaps%2F1"
    monkeypatch.setattr(router_module, "settings", dataclasses.replace(router_module.settings, frontend_login_redirect_url=entry))
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)

    assert _callback(app_client, code="auth-code", state=state).headers["location"] == entry


def test_withdrawn_account_login_is_redirected_not_json(app_client, db_session, monkeypatch, kakao_configured):
    """탈퇴 계정의 재로그인도 JSON이 아니라 302다. 스펙에 맞는 값이 없어 server_error로 간다(auth/for_Root.md)."""
    from datetime import datetime, timezone

    _mock_kakao_login(monkeypatch, kakao_id=77)
    db_session.add(User(provider="kakao", provider_user_id="77", display_name="탈퇴자", deleted_at=datetime.now(timezone.utc)))
    db_session.flush()
    state = _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="auth-code", state=state), "server_error")


def _assert_rejected_without_login(resp, db_session):
    _assert_failed_with(resp, "invalid_state", db_session)


def test_callback_link_opened_in_another_browser_is_rejected(app_client, db_session, monkeypatch, kakao_configured):
    """로그인 CSRF — 공격자가 시작한 로그인의 콜백 링크를 피해자 브라우저(쿠키 없음)가 연다."""
    _mock_kakao_login(monkeypatch)
    attacker_state = _start_login(_other_browser(app_client))

    victim = _other_browser(app_client)
    resp = _callback(victim, code="attacker-code", state=attacker_state)

    _assert_rejected_without_login(resp, db_session)


def test_callback_with_state_from_a_different_login_is_rejected(app_client, db_session, monkeypatch, kakao_configured):
    """피해자도 자기 로그인을 시작해 쿠키가 있지만, 공격자의 state가 붙은 링크는 쿠키와 달라 거절된다."""
    _mock_kakao_login(monkeypatch)
    attacker_state = _start_login(_other_browser(app_client))
    _start_login(app_client)

    resp = _callback(app_client, code="attacker-code", state=attacker_state)

    _assert_rejected_without_login(resp, db_session)


def test_callback_without_state_param_is_rejected(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    _start_login(app_client)

    resp = _callback(app_client, code="auth-code")

    _assert_rejected_without_login(resp, db_session)


def test_callback_without_state_cookie_is_rejected(app_client, db_session, monkeypatch):
    _mock_kakao_login(monkeypatch)

    resp = _callback(app_client, code="auth-code", state="anything")

    _assert_rejected_without_login(resp, db_session)


def test_callback_with_tampered_or_expired_state_cookie_is_rejected(app_client, db_session, monkeypatch):
    from auth import core
    from common.settings import settings as real_settings

    _mock_kakao_login(monkeypatch)
    forged = core.create_state_cookie_value("forged-state", secret="not-the-secret", issued_at=int(time.time()))
    expired = core.create_state_cookie_value(
        "old-state", secret=real_settings.session_secret, issued_at=int(time.time()) - core.STATE_TTL_SECONDS - 5,
    )
    for value, state in ((forged, "forged-state"), (expired, "old-state")):
        client = _other_browser(app_client)
        client.cookies.set("kakao_oauth_state", value, path="/auth/kakao")
        resp = _callback(client, code="auth-code", state=state)
        _assert_rejected_without_login(resp, db_session)


def test_callback_link_cannot_be_used_twice(app_client, monkeypatch, kakao_configured):
    """성공하면 state 쿠키가 지워져 같은 링크를 다시 열면 거절된다."""
    _mock_kakao_login(monkeypatch)
    state = _start_login(app_client)
    params = {"code": "auth-code", "state": state}

    first = app_client.get("/auth/kakao/callback", params=params, follow_redirects=False)
    assert _login_error(first) is None
    assert _is_cleared(first, "kakao_oauth_state")

    _assert_failed_with(app_client.get("/auth/kakao/callback", params=params, follow_redirects=False), "invalid_state")


def test_state_cookie_is_cleared_on_failure_too(app_client, monkeypatch, kakao_configured):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(400, {"error": "invalid_grant"}))
    state = _start_login(app_client)

    _assert_failed_with(_callback(app_client, code="bad-code", state=state), "kakao_failed")
    _assert_failed_with(_callback(app_client, code="bad-code", state=state), "invalid_state")   # 같은 링크는 다시 못 쓴다


def test_state_cookie_is_not_a_session(app_client, kakao_configured):
    """state 쿠키 값을 session 쿠키로 보내도 로그인되지 않는다 — 용도가 다른 서명이다."""
    _start_login(app_client)
    state_cookie_value = app_client.cookies.get("kakao_oauth_state", path="/auth/kakao")

    resp = _other_browser(app_client).get("/auth/me", cookies={"session": state_cookie_value})

    assert resp.status_code == 401


def test_me_returns_current_user(app_client, db_session):
    _seed_user(db_session, user_id="user_1", display_name="철수")
    resp = app_client.get("/auth/me", cookies=session_cookie("user_1"))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "user_1", "display_name": "철수"}


def test_me_without_cookie_is_401(app_client):
    resp = app_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_me_for_unknown_user_is_401(app_client):
    resp = app_client.get("/auth/me", cookies=session_cookie("no-such-user"))
    assert resp.status_code == 401


def test_patch_me_updates_display_name(app_client, db_session):
    _seed_user(db_session, user_id="user_1", display_name="철수")
    resp = app_client.patch("/auth/me", json={"display_name": "  새이름 "}, cookies=session_cookie("user_1"))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "user_1", "display_name": "새이름"}

    assert app_client.get("/auth/me", cookies=session_cookie("user_1")).json()["display_name"] == "새이름"


def test_patch_me_accepts_50_chars(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    resp = app_client.patch("/auth/me", json={"display_name": "가" * 50}, cookies=session_cookie("user_1"))
    assert resp.status_code == 200


def test_patch_me_rejects_invalid_names_with_validation_error(app_client, db_session):
    _seed_user(db_session, user_id="user_1", display_name="철수")
    for bad in ["", "   ", "가" * 51]:
        resp = app_client.patch("/auth/me", json={"display_name": bad}, cookies=session_cookie("user_1"))
        assert resp.status_code == 422, bad
        assert resp.json()["code"] == "VALIDATION_ERROR"
    assert app_client.patch("/auth/me", json={}, cookies=session_cookie("user_1")).status_code == 422

    assert app_client.get("/auth/me", cookies=session_cookie("user_1")).json()["display_name"] == "철수"


def test_patch_me_without_cookie_is_401(app_client):
    resp = app_client.patch("/auth/me", json={"display_name": "새이름"})
    assert resp.status_code == 401


def test_patch_me_after_withdraw_is_401(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    app_client.post("/auth/withdraw", cookies=session_cookie("user_1"))
    resp = app_client.patch("/auth/me", json={"display_name": "새이름"}, cookies=session_cookie("user_1"))
    assert resp.status_code == 401


def test_logout_clears_cookie(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    resp = app_client.post("/auth/logout", cookies=session_cookie("user_1"))
    assert resp.status_code == 204
    assert "session=" in resp.headers.get("set-cookie", "")


def test_logout_without_cookie_is_401(app_client):
    resp = app_client.post("/auth/logout")
    assert resp.status_code == 401


def test_withdraw_soft_deletes_user_and_clears_cookie(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    resp = app_client.post("/auth/withdraw", cookies=session_cookie("user_1"))
    assert resp.status_code == 204
    assert "session=" in resp.headers.get("set-cookie", "")

    db_session.expire_all()
    row = db_session.get(User, "user_1")
    assert row.deleted_at is not None


def test_withdraw_without_cookie_is_401(app_client):
    resp = app_client.post("/auth/withdraw")
    assert resp.status_code == 401


def test_me_after_withdraw_is_401(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    withdraw_resp = app_client.post("/auth/withdraw", cookies=session_cookie("user_1"))
    assert withdraw_resp.status_code == 204

    resp = app_client.get("/auth/me", cookies=session_cookie("user_1"))
    assert resp.status_code == 401


def test_missing_cookie_via_real_asgi_app_returns_envelope():
    """auth/mentor-review-plan.md·auth/for_Root.md(루트 확인·결정 필요 3번)가 남겨둔 후속 —
    throwaway 앱이 아니라 main.asgi_app(실제 CORS 배선까지 포함) + 실제 등록된 보호 라우트
    (/auth/me)로 401 봉투가 나오는지 확인한다. dependency_overrides 없이 main.app을 그대로
    쓰므로 db_session 픽스처가 필요 없다 — 쿠키가 없으면 DB에 닿기도 전에 막힌다.

    common/tests/test_errors.py::test_500_through_the_real_stack_has_cors_headers와 같은 패턴
    (TestClient를 `with`로 감싸지 않는다 — lifespan을 안 태우므로 realtime dispatcher가
    실제 DATABASE_URL의 event_log를 건드리지 않는다)."""
    from main import asgi_app

    response = TestClient(asgi_app).get("/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

"""구글 로그인(#1514) — 카카오와 같은 흐름(state 쿠키, 게스트 합치기, 실패 302)을 같이 쓰므로 구글만 다른 곳을 본다.

시작 주소와 요청 범위(이메일을 받지 않는다), 키가 없을 때 「준비 중」, 콜백 성공·실패, 게스트 전환.
"""

import dataclasses
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from auth import core, service
from auth.models import User, UserIdentity
from auth.testing import create_guest, session_cookie
from auth.tests.test_service import _FakeResponse

LOGIN_URL = "http://localhost:5173/login"
REDIRECT = "http://localhost:8000/auth/google/callback"


@pytest.fixture()
def google_configured(monkeypatch):
    import auth.router as router_module

    monkeypatch.setattr(router_module, "settings", dataclasses.replace(
        router_module.settings,
        google_client_id="google-client-id", google_redirect_uri=REDIRECT, frontend_login_redirect_url=LOGIN_URL,
    ))


def _mock_google(monkeypatch, *, sub="1080000000000000000001", name="구글 민수"):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"access_token": "fake-token"}))
    monkeypatch.setattr(service.httpx, "get", lambda url, **kw: _FakeResponse(200, {"sub": sub, "name": name}))


def _start(client) -> str:
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _callback(client, **params):
    return client.get("/auth/google/callback", params=params, follow_redirects=False)


def _login_error(resp) -> str | None:
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query).get("login_error", [None])[0]


def test_login_redirects_to_google_asking_only_openid_profile(app_client, google_configured):
    resp = app_client.get("/auth/google/login", follow_redirects=False)

    location = urlparse(resp.headers["location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query["client_id"] == ["google-client-id"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == ["openid profile"]   # 이메일을 받지 않는다(기획안 개인정보 표)
    set_cookie = resp.headers["set-cookie"].lower()
    assert "google_oauth_state=" in set_cookie and "path=/auth/google;" in set_cookie and "httponly" in set_cookie


def test_login_without_google_keys_sends_back_unavailable_not_500(app_client, monkeypatch):
    import auth.router as router_module

    monkeypatch.setattr(router_module, "settings", dataclasses.replace(
        router_module.settings, google_client_id="", frontend_login_redirect_url=LOGIN_URL,
    ))
    assert _login_error(app_client.get("/auth/google/login", follow_redirects=False)) == "google_unavailable"


def test_callback_creates_google_user_and_sets_session(app_client, db_session, monkeypatch, google_configured):
    _mock_google(monkeypatch)
    resp = _callback(app_client, code="auth-code", state=_start(app_client))

    assert _login_error(resp) is None
    assert "session" in resp.cookies
    row = db_session.execute(
        select(User).join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == "google", UserIdentity.provider_user_id == "1080000000000000000001")
    ).scalar_one()
    assert row.display_name == "구글 민수"


def test_google_failure_is_google_failed(app_client, db_session, monkeypatch, google_configured):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(400, {"error": "invalid_grant"}))
    resp = _callback(app_client, code="bad", state=_start(app_client))

    assert _login_error(resp) == "google_failed"
    assert db_session.execute(select(User)).first() is None


def test_userinfo_without_sub_is_google_failed(app_client, monkeypatch, google_configured):
    _mock_google(monkeypatch, sub="")
    assert _login_error(_callback(app_client, code="c", state=_start(app_client))) == "google_failed"


def test_kakao_state_cookie_does_not_open_the_google_callback(app_client, monkeypatch, google_configured):
    """state 쿠키는 제공자마다 이름과 경로가 따로다 — 카카오로 시작한 state로 구글 콜백을 통과할 수 없다."""
    _mock_google(monkeypatch)
    app_client.cookies.set("kakao_oauth_state", "x.1.y")
    assert _login_error(_callback(app_client, code="c", state="x")) == "invalid_state"


def test_guest_who_logs_in_with_google_keeps_their_account(app_client, db_session, monkeypatch, google_configured):
    """게스트 전환도 카카오와 같다 — 처음 쓰는 구글 계정이면 게스트 계정에 구글 로그인을 붙인다(#560, #694)."""
    guest = create_guest(db_session, "guest_1", display_name="게스트 이름")
    db_session.commit()
    app_client.cookies.update(session_cookie(guest.id))
    _mock_google(monkeypatch, sub="g-77")

    resp = _callback(app_client, code="c", state=_start(app_client))

    assert parse_qs(urlparse(resp.headers["location"]).query)["guest_merged"] == ["true"]
    identity = db_session.execute(select(UserIdentity).where(UserIdentity.provider == "google")).scalar_one()
    assert identity.user_id == guest.id and identity.provider_user_id == "g-77"


def test_display_name_falls_back_to_sub_when_google_name_is_empty():
    assert core.display_name_from_google_profile({"sub": "123", "name": "  "}) == "user_123"
    assert core.display_name_from_google_profile({"sub": "123", "name": "민수"}) == "민수"

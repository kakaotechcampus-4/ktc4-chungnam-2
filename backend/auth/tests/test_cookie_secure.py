"""Set-Cookie의 Secure는 `settings.cookie_secure`가 정한다(#810) — 환경 이름(is_prod)이 아니다. 기본값은 staging·prod에서 참,
COOKIE_SECURE=0이면 거짓이다(common/tests/test_settings.py). 여기서는 auth가 세 쿠키(state·세션·선택 대기) 모두에 그 값을 쓰는지 본다."""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

import auth.router as router_module
from auth.testing import create_kakao_user
from auth.tests.test_router import LOGIN_URL, _callback, _mock_kakao_login, _start_login


def _configure(monkeypatch, *, cookie_secure: bool):
    """테스트 환경은 is_prod가 거짓이다 — cookie_secure=True에서 Secure가 붙으면 환경 이름이 아니라 설정을 따른다는 뜻이다.
    (환경 이름을 바꾸면 Settings가 개발용 스텁과 staging·prod 조합을 막는다.)"""
    configured = dataclasses.replace(
        router_module.settings,
        kakao_client_id="test-client-id",
        kakao_redirect_uri="http://localhost:8000/auth/kakao/callback",
        frontend_login_redirect_url=LOGIN_URL,
        cookie_secure=cookie_secure,
    )
    monkeypatch.setattr(router_module, "settings", configured)


def _https(app_client):
    """Secure 쿠키는 http로는 되돌아오지 않는다 — state 쿠키를 콜백까지 싣는 왕복 테스트는 https 주소로 연다."""
    from fastapi.testclient import TestClient

    return TestClient(app_client.app, base_url="https://testserver")


def _set_cookie(resp, name: str) -> str:
    return next(h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{name}="))


def _has_secure(header: str) -> bool:
    return "secure" in [part.strip().lower() for part in header.split(";")[1:]]


CASES = [True, False]


@pytest.mark.parametrize("cookie_secure", CASES)
def test_state_cookie_follows_cookie_secure(app_client, monkeypatch, cookie_secure):
    _configure(monkeypatch, cookie_secure=cookie_secure)

    resp = app_client.get("/auth/kakao/login", follow_redirects=False)

    assert _has_secure(_set_cookie(resp, "kakao_oauth_state")) is cookie_secure


@pytest.mark.parametrize("cookie_secure", CASES)
def test_session_cookie_follows_cookie_secure(app_client, monkeypatch, cookie_secure):
    _configure(monkeypatch, cookie_secure=cookie_secure)
    _mock_kakao_login(monkeypatch)
    client = _https(app_client)

    resp = _callback(client, code="auth-code", state=_start_login(client))

    assert _has_secure(_set_cookie(resp, "session")) is cookie_secure


@pytest.mark.parametrize("cookie_secure", CASES)
def test_pending_cookie_follows_cookie_secure(app_client, db_session, monkeypatch, cookie_secure):
    _configure(monkeypatch, cookie_secure=cookie_secure)
    create_kakao_user(db_session, "old", provider_user_id="77", deleted_at=datetime.now(timezone.utc) - timedelta(hours=1))
    _mock_kakao_login(monkeypatch, kakao_id=77)
    client = _https(app_client)

    resp = _callback(client, code="auth-code", state=_start_login(client))

    assert _has_secure(_set_cookie(resp, "pending_account")) is cookie_secure


@pytest.mark.parametrize("cookie_secure", CASES)
def test_session_cookie_set_by_a_pending_choice_follows_cookie_secure(
    app_client, db_session, monkeypatch, cookie_secure,
):
    """선택 대기에서 `restore`·`restart`가 내리는 세션 쿠키도 같은 설정을 쓴다."""
    _configure(monkeypatch, cookie_secure=cookie_secure)
    create_kakao_user(db_session, "old", provider_user_id="77", deleted_at=datetime.now(timezone.utc) - timedelta(hours=1))
    _mock_kakao_login(monkeypatch, kakao_id=77)
    client = _https(app_client)
    _callback(client, code="auth-code", state=_start_login(client))

    resp = client.post("/auth/pending", json={"choice": "restart"})

    assert resp.status_code == 201
    assert _has_secure(_set_cookie(resp, "session")) is cookie_secure


def test_no_set_cookie_in_auth_router_reads_is_prod():
    """회귀 — secure 인자가 환경 이름으로 되돌아가지 않는다."""
    import inspect

    assert "secure=settings.is_prod" not in inspect.getsource(router_module)

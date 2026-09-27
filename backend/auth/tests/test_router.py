"""auth/router.py 통합 테스트 — 실제 PostgreSQL 필요(conftest.py 참고), main.app을 그대로 태운다.

AUTH_MODE는 테스트 환경에서 기본 dev다(common/settings.py) — 다른 모든 모듈의 통합 테스트와
같은 방식으로 `cookies={"session": user_id}`를 그대로 쓴다(auth/deps.py 모듈 docstring 참고).
카카오 콜백만 dev/real 구분 없이 항상 실제 service.login_with_kakao_code를 타므로, 그 안의
httpx 호출만 몬키패치한다.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from auth import service
from auth.models import User
from auth.tests.test_service import _FakeResponse


def _seed_user(db_session, *, user_id="user_1", display_name="철수"):
    row = User(id=user_id, provider="kakao", provider_user_id=f"kakao_{user_id}", display_name=display_name)
    db_session.add(row)
    db_session.flush()
    return row


def test_kakao_callback_creates_user_and_sets_session_cookie(app_client, db_session, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(200, {"access_token": "fake-token"})

    def fake_get(url, **kwargs):
        return _FakeResponse(200, {"id": 7, "kakao_account": {"profile": {"nickname": "민수"}}})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    monkeypatch.setattr(service.httpx, "get", fake_get)

    resp = app_client.get("/auth/kakao/callback", params={"code": "auth-code"}, follow_redirects=False)

    assert resp.status_code == 302
    assert "session" in resp.cookies

    row = db_session.execute(select(User).where(User.provider_user_id == "7")).scalar_one()
    assert row.display_name == "민수"


def test_kakao_callback_without_code_is_422(app_client):
    resp = app_client.get("/auth/kakao/callback")
    assert resp.status_code == 422


def test_kakao_callback_surfaces_kakao_failure_as_unauthorized_envelope(app_client, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(400, {"error": "invalid_grant"})

    monkeypatch.setattr(service.httpx, "post", fake_post)

    resp = app_client.get("/auth/kakao/callback", params={"code": "bad-code"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_me_returns_current_user(app_client, db_session):
    _seed_user(db_session, user_id="user_1", display_name="철수")
    resp = app_client.get("/auth/me", cookies={"session": "user_1"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "user_1", "display_name": "철수"}


def test_me_without_cookie_is_401(app_client):
    resp = app_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_me_for_unknown_user_is_401(app_client):
    resp = app_client.get("/auth/me", cookies={"session": "no-such-user"})
    assert resp.status_code == 401


def test_logout_clears_cookie(app_client):
    resp = app_client.post("/auth/logout", cookies={"session": "user_1"})
    assert resp.status_code == 204
    assert "session=" in resp.headers.get("set-cookie", "")


def test_logout_without_cookie_is_401(app_client):
    resp = app_client.post("/auth/logout")
    assert resp.status_code == 401


def test_withdraw_soft_deletes_user_and_clears_cookie(app_client, db_session):
    _seed_user(db_session, user_id="user_1")
    resp = app_client.post("/auth/withdraw", cookies={"session": "user_1"})
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
    withdraw_resp = app_client.post("/auth/withdraw", cookies={"session": "user_1"})
    assert withdraw_resp.status_code == 204

    resp = app_client.get("/auth/me", cookies={"session": "user_1"})
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

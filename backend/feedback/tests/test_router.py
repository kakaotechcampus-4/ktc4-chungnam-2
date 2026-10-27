"""POST /feedback — main.app을 그대로 태운다. 인증은 서명된 세션 쿠키(auth.testing)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth.testing import ensure_users, session_cookie
from common.ratelimit import SlidingWindowLimiter
from feedback import api
from feedback.models import Feedback


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(api, "submit_limiter", SlidingWindowLimiter(10, window_s=3600.0))


@pytest.fixture()
def client(app_client, db_session):
    ensure_users(db_session, "user_a", "user_b")
    db_session.commit()   # 요청이 실패해 롤백돼도 users 행은 남게 한다
    c = TestClient(app_client.app, cookies=session_cookie("user_a"))
    yield c
    c.close()


def test_requires_login(app_client):
    r = app_client.post("/feedback", json={"message": "안녕"})
    assert r.status_code == 401


def test_saves_and_returns_receipt_with_defaults(client, db_session):
    r = client.post("/feedback", json={"message": "  앱이 좋아요  "})

    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "created_at"}
    row = db_session.execute(select(Feedback)).scalar_one()
    assert (row.id, row.user_id, row.category, row.message, row.map_id) == (body["id"], "user_a", "other", "앱이 좋아요", None)


def test_category_and_map_id_are_saved(client, db_session):
    r = client.post("/feedback", json={"message": "버그", "category": "bug", "map_id": "whatever"})

    assert r.status_code == 201
    row = db_session.execute(select(Feedback)).scalar_one()
    assert (row.category, row.map_id) == ("bug", "whatever")


@pytest.mark.parametrize("payload", [
    {"message": ""},
    {"message": "   "},
    {"message": "a" * 1001},
    {},
    {"message": "x", "category": "praise"},
    {"message": "x", "extra": 1},
])
def test_invalid_requests_are_422_and_not_saved(client, db_session, payload):
    r = client.post("/feedback", json=payload)

    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert db_session.execute(select(Feedback)).first() is None


def test_eleventh_submission_in_an_hour_is_429_per_user(client, app_client, db_session):
    for i in range(10):
        assert client.post("/feedback", json={"message": f"m{i}"}).status_code == 201

    r = client.post("/feedback", json={"message": "m10"})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    assert len(db_session.execute(select(Feedback)).all()) == 10

    other = TestClient(app_client.app, cookies=session_cookie("user_b"))
    assert other.post("/feedback", json={"message": "다른 사람"}).status_code == 201


def test_invalid_requests_do_not_use_the_limit(client, monkeypatch):
    monkeypatch.setattr(api, "submit_limiter", SlidingWindowLimiter(1, window_s=3600.0))
    assert client.post("/feedback", json={"message": " "}).status_code == 422
    assert client.post("/feedback", json={"message": "ok"}).status_code == 201


def test_limit_comes_from_settings():
    from common.settings import settings

    assert settings.feedback_per_hour == 10

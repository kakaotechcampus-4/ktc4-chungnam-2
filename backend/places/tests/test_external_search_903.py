"""GET /places/external-search (#903) — 검색어 그대로 카카오맵 검색 링크. DB·네트워크 없이 돈다."""

import logging

import pytest

import main  # noqa: F401 — 순환 import 방지
from fastapi.testclient import TestClient

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from main import app


@pytest.fixture()
def client():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="u1")
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("q,encoded", [
    ("성수 칼국수", "%EC%84%B1%EC%88%98%20%EC%B9%BC%EA%B5%AD%EC%88%98"),
    ("a#b&c", "a%23b%26c"),
])
def test_returns_query_and_url(client, q, encoded):
    r = client.get("/places/external-search", params={"q": q})
    assert r.status_code == 200
    assert r.json() == {"query": q, "url": "https://map.kakao.com/link/search/" + encoded,
                        "naver_url": "https://map.naver.com/p/search/" + encoded}   # #1513


def test_query_is_trimmed(client):
    assert client.get("/places/external-search", params={"q": "  서울숲  "}).json()["query"] == "서울숲"


@pytest.mark.parametrize("q", ["", "   ", "가" * 51])
def test_length_validation(client, q):
    r = client.get("/places/external-search", params={"q": q})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


def test_missing_q_is_422(client):
    assert client.get("/places/external-search").status_code == 422


def test_accepts_50_chars(client):
    assert client.get("/places/external-search", params={"q": "가" * 50}).status_code == 200


def test_requires_login():
    assert TestClient(app).get("/places/external-search", params={"q": "서울숲"}).status_code == 401


def test_query_is_not_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.get("/places/external-search", params={"q": "비밀검색어"})
    assert "비밀검색어" not in caplog.text

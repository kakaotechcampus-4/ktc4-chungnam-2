"""#1681 — GET /places/{placeId}/photos: 핀을 찍기 전 검색 결과의 블로그 사진. 사진 찾기는 places.api.place_photos 그대로.
DB·카카오 없이 돈다(장소 조회, 사진, 상한을 대역으로)."""

import pytest

import main  # noqa: F401 — 순환 import 방지
from fastapi.testclient import TestClient

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from common.errors import AppError
from main import app
from places import api

PHOTO = api.PlacePhoto(thumbnail_url="https://search1.kakaocdn.net/thumb/1", link_url="https://blog.naver.com/a/1", site_name="네이버블로그")


@pytest.fixture()
def client(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(api, "get_places", lambda ids, db=None: {i: object() for i in ids if i == "place_known"})
    monkeypatch.setattr(api, "place_photos", lambda place_id, db=None: calls.append(place_id) or [PHOTO])
    monkeypatch.setattr(api, "check_photo_rate", lambda user_id: None)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="u1")
    app.dependency_overrides[get_db_session] = lambda: None
    yield TestClient(app), calls
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_session, None)


def test_known_place_returns_photos(client):
    c, calls = client
    r = c.get("/places/own:place_known/photos")
    assert r.status_code == 200
    assert r.json() == [{"thumbnail_url": PHOTO.thumbnail_url, "link_url": PHOTO.link_url, "site_name": "네이버블로그"}]
    assert calls == ["place_known"]


def test_unknown_place_is_404_without_searching(client):
    c, calls = client
    r = c.get("/places/own:nope/photos")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert calls == []


def test_kakao_result_is_empty_without_counting(client, monkeypatch):
    c, calls = client
    counted: list[str] = []
    monkeypatch.setattr(api, "check_photo_rate", lambda user_id: counted.append(user_id))
    r = c.get("/places/12345678/photos")
    assert r.status_code == 200 and r.json() == []
    assert calls == [] and counted == []


def test_rate_limit_is_429(client, monkeypatch):
    c, calls = client

    def limited(user_id):
        raise AppError("RATE_LIMITED")

    monkeypatch.setattr(api, "check_photo_rate", limited)
    assert c.get("/places/own:place_known/photos").status_code == 429
    assert calls == []


def test_needs_login():
    assert TestClient(app).get("/places/own:place_known/photos").status_code == 401

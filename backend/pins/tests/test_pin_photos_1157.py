"""#1157 — GET /pins/{pinId}/photos: 핀이 가리키는 자체 DB 장소의 블로그 사진. 사진 찾기는 places.api 가 하고
여기서는 핀에서 장소를 고르고, 권한(구성원만)과 실시간 핀 예외를 본다. 카카오는 부르지 않는다."""

import pytest

from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.errors import AppError
from main import app
from places import api as places_api
from pins.tests.test_live_pins_386 import _post_live
from pins.tests.test_pins_api import _auth, _insert_pin

PHOTO = places_api.PlacePhoto(thumbnail_url="https://search1.kakaocdn.net/thumb/1", link_url="https://blog.naver.com/a/1", site_name="네이버블로그")


@pytest.fixture()
def photos(monkeypatch):
    calls: list[str] = []

    def fake(place_id, db=None):
        calls.append(place_id)
        return [PHOTO]

    monkeypatch.setattr(places_api, "place_photos", fake)
    monkeypatch.setattr(places_api, "check_photo_rate", lambda user_id: None)
    return calls


def test_db_pin_returns_photos_of_its_place(app_client, db_session, photos):
    pin = _insert_pin(db_session, place_id="place_nurukmok")
    resp = app_client.get(f"/pins/{pin.id}/photos", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json() == [{"thumbnail_url": PHOTO.thumbnail_url, "link_url": PHOTO.link_url, "site_name": "네이버블로그"}]
    assert photos == ["place_nurukmok"]


def test_live_pin_has_no_address_so_returns_empty_without_searching(app_client, photos):
    pin_id = _post_live(app_client).json()["id"]
    resp = app_client.get(f"/pins/{pin_id}/photos", cookies=_auth())
    assert resp.status_code == 200 and resp.json() == []
    assert photos == []


def test_non_member_gets_404(app_client, db_session, photos):
    pin = _insert_pin(db_session)
    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership({})
    resp = app_client.get(f"/pins/{pin.id}/photos", cookies=_auth())
    assert resp.status_code == 404
    assert photos == []


def test_rate_limit_is_429(app_client, db_session, monkeypatch):
    pin = _insert_pin(db_session)

    def limited(user_id):
        raise AppError("RATE_LIMITED")

    monkeypatch.setattr(places_api, "check_photo_rate", limited)
    assert app_client.get(f"/pins/{pin.id}/photos", cookies=_auth()).status_code == 429

"""#569 — 같은 지도에서 같은 가게가 실시간 핀과 자체 DB 핀으로 따로 생기지 않는다(기준은 카카오 장소 ID).

생성(search·live)·승격(resolve) 세 경로 모두 409 PIN_DUPLICATE(detail.pin_id = 이미 있는 핀)이고 자동 병합은 없다.
"""

import uuid

from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.tests.test_pins_api import KALGUKSU, _auth, _events, _insert_pin

LIVE = {"source": "live", "category": "음식점", "kakao_place_id": "kakao:1001", "search_query": "성수 칼국수"}
HINT = {"place_name": KALGUKSU["place_name"], "lat": KALGUKSU["lat"], "lng": KALGUKSU["lng"]}


def _post(app_client, body, map_id="map_1"):
    return app_client.post(f"/maps/{map_id}/pins", json=body, cookies=_auth())


def _kalguksu_row(fake_places):
    return next(r for r in fake_places.rows if r.key == "seongsu-kalguksu")


def test_search_pin_is_409_when_a_live_pin_has_the_hint_kakao_id(app_client):
    live = _post(app_client, LIVE).json()
    resp = _post(app_client, KALGUKSU)   # place_id kakao:1001 — 실시간 핀과 같은 카카오 ID
    assert resp.status_code == 409 and resp.json()["detail"]["pin_id"] == live["id"]


def test_search_pin_is_409_when_places_row_recorded_the_live_pins_kakao_id(app_client, fake_places):
    _kalguksu_row(fake_places).kakao_place_id = "kakao:OLD"
    live = _post(app_client, {**LIVE, "kakao_place_id": "kakao:OLD"}).json()
    resp = _post(app_client, KALGUKSU)   # 힌트 ID는 다르지만 같은 자체 DB 장소에 기록된 ID가 실시간 핀의 것
    assert resp.status_code == 409 and resp.json()["detail"]["pin_id"] == live["id"]


def test_live_pin_is_409_when_the_recorded_place_already_has_a_pin(app_client):
    db_pin = _post(app_client, KALGUKSU).json()   # 만들며 카카오 ID가 자체 DB 장소에 기록된다
    resp = _post(app_client, LIVE)
    assert resp.status_code == 409 and resp.json()["detail"]["pin_id"] == db_pin["id"]


def test_resolve_is_409_for_another_live_pin_of_the_same_place(app_client, fake_places, db_session):
    _kalguksu_row(fake_places).kakao_place_id = "kakao:OLD"
    other = _post(app_client, {**LIVE, "kakao_place_id": "kakao:OLD"}).json()
    mine = _post(app_client, LIVE).json()
    resp = app_client.post(f"/pins/{mine['id']}/resolve", json=HINT, cookies=_auth())
    assert resp.status_code == 409 and resp.json()["detail"]["pin_id"] == other["id"]
    assert _events(db_session, type="pin.updated") == []


def test_nothing_is_merged_on_conflict(app_client, db_session):
    live = _post(app_client, LIVE).json()
    assert _post(app_client, KALGUKSU).status_code == 409
    assert db_session.query(PinRow).filter(PinRow.map_id == "map_1", PinRow.deleted_at.is_(None)).count() == 1
    assert db_session.get(PinRow, uuid.UUID(live["id"])).source == "live"


def test_other_map_is_not_affected(app_client, db_session):
    db_session.add(PinRow(
        map_id="map_2", category="음식점", kind="일반", origin="direct", source="live", visibility="public",
        created_by="user_1", kakao_place_id="kakao:1001", search_query="성수 칼국수",
    ))
    db_session.commit()
    assert _post(app_client, KALGUKSU).status_code == 201


def test_place_without_kakao_id_is_not_affected(app_client):
    assert _post(app_client, {**LIVE, "kakao_place_id": "kakao:5555"}).status_code == 201   # 기록된 자체 DB 장소 없음
    assert _post(app_client, {**KALGUKSU, "place_id": "kakao:1001", "place_name": "성수 칼국수"}).status_code == 201


def test_different_place_is_not_affected(app_client):
    _post(app_client, LIVE)
    other = {"category": "카페", "place_id": "kakao:1002", "place_name": "온도 커피 성수", "lat": 37.5439, "lng": 127.0556}
    assert _post(app_client, other).status_code == 201


def test_list_live_kakao_place_ids_returns_only_ids_of_live_pins_on_the_map(app_client, db_session):
    _post(app_client, LIVE)
    _post(app_client, {**LIVE, "kakao_place_id": "kakao:2002"})
    _insert_pin(db_session)                                   # db 핀은 제외
    gone = _post(app_client, {**LIVE, "kakao_place_id": "kakao:3003"}).json()
    app_client.delete(f"/pins/{gone['id']}", cookies=_auth())  # 삭제된 핀은 제외
    db_session.add(PinRow(
        map_id="map_2", category="음식점", kind="일반", origin="direct", source="live", visibility="public",
        created_by="user_1", kakao_place_id="kakao:9009", search_query="다른 지도",
    ))
    db_session.commit()
    assert sorted(pins_api.list_live_kakao_place_ids(db_session, map_id="map_1")) == ["kakao:1001", "kakao:2002"]
    assert pins_api.list_live_kakao_place_ids(db_session, map_id="map_2") == ["kakao:9009"]
    assert pins_api.list_live_kakao_place_ids(db_session, map_id="map_none") == []

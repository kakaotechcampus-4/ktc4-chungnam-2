"""#501 — POST /pins/{pinId}/resolve: 실시간 핀을 자체 DB 핀으로 승격. 핀 id·반응·확정 항목은 그대로, 힌트는 어디에도 남기지 않는다.

짝 없음·이미 db 핀·AI/확정 핀은 200 변화 없음·이벤트 없음. 같은 지도에 그 장소 핀이 이미 있으면 409 PIN_DUPLICATE(자동 병합 금지).
"""

import logging

from sqlalchemy import select

from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth, _events, _insert_pin

LIVE = {"source": "live", "category": "음식점", "kakao_place_id": "kakao:1001", "search_query": "성수 칼국수", "memo": "점심"}
HINT = {"place_name": KALGUKSU["place_name"], "lat": KALGUKSU["lat"], "lng": KALGUKSU["lng"]}
SECRET_ADDRESS = "서울 성동구 비밀주소로 99"


def _live(app_client, user="user_1", **overrides):
    resp = app_client.post("/maps/map_1/pins", json={**LIVE, **overrides}, cookies=_auth(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _resolve(app_client, pin_id, body=HINT, user="user_1"):
    return app_client.post(f"/pins/{pin_id}/resolve", json=body, cookies=_auth(user))


def _row(db_session, pin_id) -> PinRow:
    db_session.expire_all()
    return db_session.execute(select(PinRow).where(PinRow.id == pin_id)).scalar_one()


def test_match_promotes_live_pin_to_db_pin_in_place(app_client, db_session):
    pin = _live(app_client)
    resp = _resolve(app_client, pin["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == pin["id"] and body["source"] == "db"
    assert body["place_name"] == "성수 칼국수" and (body["lat"], body["lng"]) == (37.5445, 127.0561)
    assert body["memo"] == "점심"
    row = _row(db_session, pin["id"])
    assert row.source == "db" and row.place_id and row.kakao_place_id is None and row.search_query is None
    assert len(_events(db_session, type="pin.updated")) == 1


def test_any_member_can_resolve_and_reactions_survive(app_client, db_session):
    pin = _live(app_client)
    assert app_client.put(f"/pins/{pin['id']}/reaction", json={"type": "like"}, cookies=_auth("user_2")).status_code == 200
    resp = _resolve(app_client, pin["id"], user="user_2")
    assert resp.status_code == 200 and resp.json()["source"] == "db"
    assert resp.json()["my_reaction"]["type"] == "like"
    assert db_session.execute(select(ReactionRow).where(ReactionRow.pin_id == _row(db_session, pin["id"]).id)).scalars().all()


def test_no_match_is_200_unchanged_and_no_event(app_client, db_session):
    pin = _live(app_client)
    resp = _resolve(app_client, pin["id"], {"place_name": "없는 가게", "lat": 35.0, "lng": 129.0})
    assert resp.status_code == 200 and resp.json()["source"] == "live"
    assert _row(db_session, pin["id"]).kakao_place_id == "kakao:1001"
    assert _events(db_session, type="pin.updated") == []


def test_already_db_pin_is_200_unchanged_and_no_event(app_client, db_session):
    pin = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    resp = _resolve(app_client, pin["id"])
    assert resp.status_code == 200 and resp.json()["id"] == pin["id"] and resp.json()["source"] == "db"
    assert _events(db_session, type="pin.updated") == []


def test_ai_or_confirmed_pin_is_unchanged(app_client, db_session):
    for kind in ("AI추천", "확정"):
        row = _insert_pin(db_session, kind=kind)
        resp = _resolve(app_client, str(row.id))
        assert resp.status_code == 200 and resp.json()["kind"] == kind
    assert _events(db_session, type="pin.updated") == []


def test_confirmed_live_pin_is_not_promoted(app_client, db_session):
    pin = _live(app_client)
    _row(db_session, pin["id"]).kind = "확정"
    db_session.commit()
    resp = _resolve(app_client, pin["id"])
    assert resp.status_code == 200 and resp.json()["source"] == "live"
    assert _events(db_session, type="pin.updated") == []


def test_existing_pin_for_that_place_is_409_and_nothing_merges(app_client, db_session):
    existing = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    live = _live(app_client, kakao_place_id="kakao:OTHER")   # 같은 카카오 ID면 생성 단계에서 막힌다(#569)
    resp = _resolve(app_client, live["id"])
    assert resp.status_code == 409 and resp.json()["detail"]["pin_id"] == existing["id"]
    row = _row(db_session, live["id"])
    assert row.source == "live" and row.kakao_place_id == "kakao:OTHER" and row.deleted_at is None
    assert _events(db_session, type="pin.updated") == []


def test_category_comes_from_the_pin_not_the_hint(app_client):
    pin = _live(app_client, category="카페", kakao_place_id="kakao:1002")
    assert _resolve(app_client, pin["id"], {"place_name": CAFE["place_name"], "lat": CAFE["lat"], "lng": CAFE["lng"]}).json()["source"] == "db"
    pin2 = _live(app_client, category="카페", kakao_place_id="kakao:9")
    assert _resolve(app_client, pin2["id"]).json()["source"] == "live"   # 칼국수 힌트는 카페 핀과 분류가 달라 짝이 없다


def test_validation_and_unknown_pin(app_client):
    pin = _live(app_client)
    assert _resolve(app_client, pin["id"], {"place_name": "", "lat": 37.5, "lng": 127.0}).status_code == 422
    assert _resolve(app_client, pin["id"], {"place_name": "x", "lat": 95, "lng": 127.0}).status_code == 422
    assert _resolve(app_client, pin["id"], {**HINT, "extra": 1}).status_code == 422
    assert _resolve(app_client, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_hint_is_never_logged_or_stored(app_client, db_session, caplog):
    pin = _live(app_client)
    with caplog.at_level(logging.DEBUG):
        resp = _resolve(app_client, pin["id"], {**HINT, "address": SECRET_ADDRESS})
    assert resp.status_code == 200 and resp.json()["source"] == "db"
    assert SECRET_ADDRESS not in resp.text and SECRET_ADDRESS not in caplog.text
    assert KALGUKSU["place_name"] not in caplog.text and "37.5445" not in caplog.text
    row = _row(db_session, pin["id"])
    stored = " ".join(str(v) for v in (row.memo, row.search_query, row.kakao_place_id, row.checks, row.reason, row.place_source))
    assert SECRET_ADDRESS not in stored and KALGUKSU["place_name"] not in stored
    for event in _events(db_session):
        assert SECRET_ADDRESS not in str(event.payload)


def test_create_passes_address_to_matcher_without_storing_it(app_client, fake_places, monkeypatch, caplog):
    seen = []
    real = fake_places.match_place
    monkeypatch.setattr("places.api.match_place", lambda hint, **kw: (seen.append(hint.address), real(hint, **kw))[1])
    with caplog.at_level(logging.DEBUG):
        resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "address": SECRET_ADDRESS}, cookies=_auth())
    assert resp.status_code == 201 and seen == [SECRET_ADDRESS]
    assert SECRET_ADDRESS not in resp.text and SECRET_ADDRESS not in caplog.text
    assert app_client.post("/maps/map_1/pins", json={**CAFE, "address": "가" * 201}, cookies=_auth()).status_code == 422

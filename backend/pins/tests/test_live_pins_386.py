"""#386 — 실시간 핀(source=live): 카카오 장소 ID·검색어·메모로 남기는 핀(스펙 PinCreateLive, #382).

이름·좌표는 받지도 저장하지도 않는다. 장소(places)가 없으니 recommend·shortlist가 쓰는 pins.api 조회는
좌표·place_id가 없는 핀을 건너뛰어야 한다.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from authz.core import Principal
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from main import app
from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.tests.test_author_display_369 import _make_map
from pins.tests.test_pins_api import KALGUKSU, _auth, _events, _insert_pin

LIVE = {
    "source": "live", "category": "음식점", "kakao_place_id": "kakao:9001",
    "search_query": "성수 곱창", "memo": "여기 곱창 맛있대",
}


def _post_live(app_client, user="user_1", **overrides):
    body = {**LIVE, **overrides}
    body = {k: v for k, v in body.items() if v is not None}
    return app_client.post("/maps/map_1/pins", json=body, cookies=_auth(user))


# ---- 생성 ----

def test_create_live_pin_returns_201_without_name_or_coordinates(app_client):
    resp = _post_live(app_client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "live"
    assert body["kakao_place_id"] == "kakao:9001"
    assert body["search_query"] == "성수 곱창"
    assert body["memo"] == "여기 곱창 맛있대"
    assert body["kind"] == "일반" and body["visibility"] == "public"
    assert body["created_by"] == "user_1" and body["created_at"]
    assert body["reaction_summary"] == {"like": 0, "against": 0}
    for absent in ("lat", "lng", "place_name", "checks"):
        assert absent not in body
    assert body["place_url"] == "https://place.map.kakao.com/9001"   # #445 — 저장하지 않고 응답 때 만든다


def test_create_live_pin_stores_only_allowed_values(app_client, db_session):
    _post_live(app_client)
    row = db_session.execute(select(PinRow).where(PinRow.kakao_place_id == "kakao:9001")).scalar_one()
    assert row.source == "live" and row.place_id is None and row.geom is None
    assert (row.kakao_place_id, row.search_query, row.memo) == ("kakao:9001", "성수 곱창", "여기 곱창 맛있대")


def test_create_live_pin_memo_is_optional_and_blank_memo_is_dropped(app_client):
    assert "memo" not in _post_live(app_client, memo=None).json()
    assert "memo" not in _post_live(app_client, kakao_place_id="kakao:9002", memo="   ").json()


@pytest.mark.parametrize("missing", ["category", "kakao_place_id", "search_query"])
def test_create_live_pin_missing_required_field_is_422(app_client, missing):
    body = {k: v for k, v in LIVE.items() if k != missing}
    resp = app_client.post("/maps/map_1/pins", json=body, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "extra", [{"place_name": "성수 곱창집"}, {"lat": 37.5, "lng": 127.0}, {"place_id": "kakao:9001"}],
)
def test_create_live_pin_refuses_name_and_coordinates(app_client, db_session, extra):
    """카카오 응답의 이름·좌표는 받지도 저장하지도 않는다(#53) — 보내면 요청 오류다."""
    resp = app_client.post("/maps/map_1/pins", json={**LIVE, **extra}, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"
    assert db_session.execute(select(PinRow)).scalars().all() == []


@pytest.mark.parametrize("category", ["숙소", "기타"])
def test_create_live_pin_for_lodging_or_etc_is_422_validation_error(app_client, category):
    resp = _post_live(app_client, category=category)
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field", ["kakao_place_id", "search_query"])
def test_create_live_pin_blank_identifiers_are_422(app_client, field):
    assert _post_live(app_client, **{field: "   "}).status_code == 422


def test_create_live_pin_too_long_memo_is_422(app_client):
    assert _post_live(app_client, memo="가" * 201).status_code == 422


def test_create_live_pin_requires_member(app_client):
    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership({})
    try:
        assert _post_live(app_client).status_code == 404
    finally:
        app.dependency_overrides.pop(get_membership_gateway, None)


# ---- 중복 ----

def test_same_kakao_place_on_same_map_is_409_pin_duplicate_with_existing_id(app_client):
    first = _post_live(app_client).json()
    resp = _post_live(app_client, user="user_2", search_query="곱창")
    assert resp.status_code == 409
    assert resp.json()["code"] == "PIN_DUPLICATE"
    assert resp.json()["detail"]["pin_id"] == first["id"]


def test_live_pin_can_be_recreated_after_delete(app_client):
    first = _post_live(app_client).json()
    assert app_client.delete(f"/pins/{first['id']}", cookies=_auth()).status_code == 204
    assert _post_live(app_client).status_code == 201


def test_live_pin_does_not_collide_with_db_pin_or_other_live_pin(app_client):
    assert app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).status_code == 201
    assert _post_live(app_client).status_code == 201
    assert _post_live(app_client, kakao_place_id="kakao:9002").status_code == 201


def test_db_pin_response_has_source_db_and_coordinates(app_client):
    body = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    assert body["source"] == "db" and "lat" in body and "lng" in body and "place_name" in body
    assert "kakao_place_id" not in body and "search_query" not in body


def test_ai_pin_is_always_db(db_session):
    """AI 핀(origin=ai)은 live가 될 수 없다 — create_ai_pin은 place_id·좌표를 필수로 받고 source='db'로만 만든다."""
    mutation = pins_api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_ai", lat=37.54, lng=127.05, created_by="user_1",
    )
    assert mutation.pin.origin == "ai" and mutation.pin.source == "db"
    assert mutation.pin.place_id == "place_ai" and mutation.pin.geom is not None


def test_check_constraint_rejects_inconsistent_source_rows(db_session):
    live_with_place = PinRow(
        map_id="map_1", category="음식점", kind="일반", origin="direct", source="live",
        place_id="place_x", kakao_place_id="kakao:1", search_query="q", visibility="public", created_by="user_1",
    )
    db_session.add(live_with_place)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    db_without_place = PinRow(
        map_id="map_1", category="음식점", kind="일반", origin="direct", source="db",
        place_id=None, geom=func.ST_SetSRID(func.ST_MakePoint(127, 37), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(db_without_place)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---- 목록·집계·이벤트 ----

def test_list_pins_returns_live_and_db_pins_together(app_client, db_session):
    _insert_pin(db_session, place_id="p_db")
    live = _post_live(app_client).json()
    listed = {p["id"]: p for p in app_client.get("/maps/map_1/pins", cookies=_auth()).json()}
    assert len(listed) == 2
    assert listed[live["id"]]["source"] == "live" and "lat" not in listed[live["id"]]
    assert sum(1 for p in listed.values() if p["source"] == "db" and "lat" in p) == 1


def test_live_pin_place_url_in_list_and_detail_and_non_kakao_id_omits_it(app_client, db_session):
    live = _post_live(app_client).json()
    other = _post_live(app_client, kakao_place_id="naver:77").json()
    url = "https://place.map.kakao.com/9001"
    listed = {p["id"]: p for p in app_client.get("/maps/map_1/pins", cookies=_auth()).json()}
    assert listed[live["id"]]["place_url"] == url
    assert "place_url" not in listed[other["id"]]
    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    detail = pins_api.get_pin_response_for_viewer(db_session, pin_id=live["id"], viewer_id="user_1", principal=principal)
    assert detail.place_url == url
    detail_other = pins_api.get_pin_response_for_viewer(db_session, pin_id=other["id"], viewer_id="user_1", principal=principal)
    assert detail_other.place_url is None


def test_list_filters_and_counts_include_live_pins(app_client):
    live = _post_live(app_client).json()
    by_cat = app_client.get("/maps/map_1/pins", params={"category": "음식점"}, cookies=_auth()).json()
    by_kind = app_client.get("/maps/map_1/pins", params={"kind": "일반"}, cookies=_auth()).json()
    by_author = app_client.get("/maps/map_1/pins", params={"created_by": "user_1"}, cookies=_auth()).json()
    assert [p["id"] for p in by_cat] == [p["id"] for p in by_kind] == [p["id"] for p in by_author] == [live["id"]]
    counts = app_client.get("/maps/map_1/counts", cookies=_auth()).json()
    assert counts["by_category"]["음식점"] == 1 and counts["by_kind"]["일반"] == 1


def test_pin_created_event_payload_has_no_name_or_coordinates(app_client, db_session):
    _post_live(app_client)
    (event,) = _events(db_session, type="pin.created")
    assert event.payload["source"] == "live" and event.payload["kakao_place_id"] == "kakao:9001"
    for absent in ("lat", "lng", "place_name"):
        assert absent not in event.payload


# ---- 반응·삭제 ----

def test_live_pin_takes_reactions_and_against_still_needs_a_reason(app_client):
    pin_id = _post_live(app_client).json()["id"]
    assert app_client.put(f"/pins/{pin_id}/reaction", json={"type": "like"}, cookies=_auth("user_2")).status_code == 200
    bad = app_client.put(f"/pins/{pin_id}/reaction", json={"type": "against"}, cookies=_auth("user_1"))
    assert bad.status_code == 422 and bad.json()["code"] == "EVIDENCE_REQUIRED"
    ok = app_client.put(
        f"/pins/{pin_id}/reaction", json={"type": "against", "reason_text": "멀어요"}, cookies=_auth("user_1"),
    )
    assert ok.status_code == 200
    pin = next(p for p in app_client.get("/maps/map_1/pins", cookies=_auth()).json() if p["id"] == pin_id)
    assert pin["reaction_summary"] == {"like": 1, "against": 1}
    assert pin["my_reaction"]["type"] == "against"


def test_live_pin_can_be_deleted_by_a_member(app_client):
    pin_id = _post_live(app_client).json()["id"]
    assert app_client.delete(f"/pins/{pin_id}", cookies=_auth("user_2")).status_code == 204
    assert app_client.get("/maps/map_1/pins", cookies=_auth()).json() == []


# ---- pins.api — recommend·shortlist가 쓰는 조회는 live 핀을 건너뛴다 ----

def _live_row(db_session, *, kakao_place_id="kakao:7001", category="음식점", created_by="user_1"):
    row = PinRow(
        map_id="map_1", category=category, kind="일반", origin="direct", source="live",
        kakao_place_id=kakao_place_id, search_query="q", visibility="public", created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_pins_api_skips_live_pins_where_a_place_or_coordinate_is_needed(db_session):
    db_pin = _insert_pin(db_session, place_id="place_db")
    live = _live_row(db_session)
    db_session.add_all([
        ReactionRow(pin_id=live.id, user_id="user_1", type="against", reason_text="조개 알러지"),
        ReactionRow(pin_id=live.id, user_id="user_2", type="like"),
        ReactionRow(pin_id=db_pin.id, user_id="user_2", type="like"),
    ])
    db_session.commit()

    coords = pins_api.get_category_pin_coordinates(db_session, map_id="map_1", category="음식점")
    assert [pin_id for pin_id, _, _ in coords] == [str(db_pin.id)]
    assert pins_api.list_place_ids_on_map(db_session, map_id="map_1") == {"place_db"}
    assert pins_api.list_disliked_place_ids(db_session, user_id="user_1", map_id="map_1", category="음식점") == []
    liked = pins_api.list_liked_pins(db_session, map_id="map_1", category="음식점", requested_by="user_1")
    assert liked == [{"place_id": "place_db", "member_ids": {"user_2"}}]
    assert set(pins_api.get_coordinates_for_pins(db_session, [str(db_pin.id), str(live.id)])) == {str(db_pin.id)}


def test_live_pin_reasons_still_reach_the_evidence_and_the_readiness_count(db_session):
    """반응·사유는 자체 DB 핀과 똑같이 근거 줄·준비 판정에 쓰인다(#382)."""
    _make_map(db_session, "map_1", {"user_1": "owner"})
    live = _live_row(db_session)
    db_session.add(ReactionRow(pin_id=live.id, user_id="user_1", type="against", reason_text="조개 알러지"))
    db_session.commit()

    reasons = pins_api.list_reasoned_reactions(db_session, map_id="map_1", category="음식점")
    assert [(r["pin_id"], r["reason_text"]) for r in reasons] == [(str(live.id), "조개 알러지")]
    assert pins_api.count_opinion_pins(db_session, map_id="map_1", category="음식점") == 1


def test_get_pin_response_for_viewer_handles_live_pin(app_client, db_session):
    live_id = _post_live(app_client).json()["id"]
    pin = pins_api.get_pin_response_for_viewer(
        db_session, pin_id=live_id, viewer_id="user_1",
        principal=Principal(user_id="user_1", map_id="map_1", role="member"),
    )
    assert pin.source == "live" and pin.lat is None and pin.lng is None and pin.place_name is None

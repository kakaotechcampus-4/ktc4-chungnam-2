"""pins 조립과 실제 places 번호표·PostgreSQL 트랜잭션의 연결 회귀(#1047·#1048)."""

import logging
from dataclasses import replace

import pytest
from sqlalchemy import func, select, text

from pins import link_import
from pins.models import Pin as PinRow
from pins.tests.test_link_import_577 import _bulk, _preview, _preview_hinted
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth, _events
from places import api as places_api
from places.models import Place, PlaceExternalId, PlaceExternalIdVote

# app_client의 FakePlaces 설치 전에 공개 함수 원본을 보관한다.
REAL_APIS = {name: getattr(places_api, name) for name in (
    "match_by_name_address", "match_address_candidates", "record_external_id", "own_places_by_external_id",
)}
URL = "https://m.place.naver.com/restaurant/1412566798/home"
REF = {"provider": "naver", "external_id": "naver:1412566798"}


@pytest.fixture
def real_number_table(app_client, db_session, fake_places, monkeypatch):
    """매칭·표 기록/조회는 실제 공개 API와 테스트 DB, 핀 검색 대역 장소도 DB에 준비한다."""
    for row in fake_places.rows:
        db_session.add(Place(
            id=row.place_id, source="permit", source_id=row.place_id, name=row.name,
            category=row.category, address="서울 성동구 성수이로 100", status="open",
            geom=func.ST_SetSRID(func.ST_MakePoint(row.lng, row.lat), 4326),
        ))
    db_session.flush()
    for name, original in REAL_APIS.items():
        def bound(*args, _original=original, db=None, **kwargs):
            return _original(*args, db=db_session, **kwargs)
        monkeypatch.setattr(places_api, name, bound)
    return fake_places.place_id("seongsu-kalguksu")


def test_hint_confirmation_then_same_link_uses_number_table(app_client, real_number_table):
    first = _preview_hinted(app_client, URL, {"name": "성수 칼국수", "address": "서울 성동구 성수이로 100"})
    assert first["result"]["matched_by"] == "hint"
    assert first["result"]["external_id"] == REF["external_id"]
    second = _preview(app_client, [URL]).json()["items"][0]
    assert second["result"]["matched_by"] == "external_id"
    assert second["result"]["matches"] == first["result"]["matches"]


@pytest.mark.parametrize("name,address,stored_name,expected", [
    ("유소바 안국역점", "서울 종로구 창덕궁1길 32 1층", "유소바", "hint"),
    ("쿄와우동", "서울 종로구 계동길 17 지하1층", "쿄와우동", "hint"),
    ("크리스엄마의 치즈케이크", "서울 종로구 창덕궁1길 39 1층 라타르타", "라타르타데라마드레데크리스코리아", "candidate"),
    ("미적재 식당", "서울 종로구 창덕궁1길 999", None, "empty"),
    ("동명 식당", "서울 종로구 창덕궁1길 998", "동명 식당", "ambiguous"),
])
def test_share_samples_against_controlled_local_rows(app_client, db_session, real_number_table, name, address, stored_name, expected):
    """공유 입력 형식 회귀용 fixture다. 실제 적재 DB나 스테이징 결과를 주장하지 않는다."""
    if stored_name:
        for index in range(2 if expected == "ambiguous" else 1):
            db_session.add(Place(
                source="permit", source_id=f"sample-{index}", name=stored_name, address=address,
                category="음식점", status="open", geom=func.ST_SetSRID(func.ST_MakePoint(126.99, 37.57), 4326),
            ))
        db_session.flush()
    item = _preview_hinted(app_client, URL, {"name": name, "address": address})
    result = item["result"]
    if expected == "hint":
        assert result["matched_by"] == "hint" and len(result["matches"]) == 1
        assert _preview(app_client, [URL]).json()["items"][0]["result"]["matched_by"] == "external_id"
    else:
        assert result["matches"] == [] and result["needs_search_query"] is True
        assert len(result.get("address_candidates", [])) == (1 if expected == "candidate" else 0)
        assert "already_pinned_pin_id" not in item


@pytest.mark.parametrize("basis", ["hint", "external_id"])
def test_existing_match_reason_is_preserved(app_client, monkeypatch, basis):
    from pins.tests.test_link_import_577 import _match, _stub_parse
    from places.schemas import LinkParseResult

    _stub_parse(monkeypatch, {URL: LinkParseResult(
        provider="naver", matches=[_match("own:sample")], matched_by=basis, needs_search_query=False,
    )})
    assert _preview(app_client, [URL]).json()["items"][0]["result"]["matched_by"] == basis


def test_address_only_candidate_has_no_already_pinned_marker(app_client, fake_places):
    row = next(r for r in fake_places.rows if r.place_id == fake_places.place_id("seongsu-kalguksu"))
    fake_places.rows = [replace(r, address="서울 성동구 성수이로 100") if r == row else r for r in fake_places.rows]
    assert app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).status_code == 201
    item = _preview_hinted(app_client, URL, {"name": "다른 상호명", "address": "서울 성동구 성수이로 100"})
    assert item["result"]["matches"] == [] and item["result"]["needs_search_query"] is True
    assert len(item["result"]["address_candidates"]) == 1
    assert "already_pinned_pin_id" not in item


def test_address_candidate_does_not_get_live_kakao_duplicate_marker(app_client, monkeypatch):
    from pins.tests.test_link_import_577 import LIVE, _match, _stub_parse
    from places.schemas import LinkParseResult

    assert app_client.post("/maps/map_1/pins", json=LIVE, cookies=_auth()).status_code == 201
    _stub_parse(monkeypatch, {"k": LinkParseResult(
        provider="kakao", kakao_place_id=LIVE["kakao_place_id"], matches=[], needs_search_query=True,
        address_candidates=[_match("own:candidate")],
    )})
    assert "already_pinned_pin_id" not in _preview(app_client, ["k"]).json()["items"][0]


def test_user_votes_are_deduplicated_and_two_users_are_trusted(app_client, db_session, real_number_table):
    # 핀을 지운 뒤 같은 사용자가 다시 고르는 상황도 한 표다.
    def choose(user):
        response = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "link_ref": REF}, cookies=_auth(user))
        assert response.status_code == 201, response.text
        pin = db_session.get(PinRow, response.json()["id"])
        db_session.delete(pin)
        db_session.commit()

    choose("user_1")
    choose("user_1")
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalIdVote)) == 1
    assert _preview(app_client, [URL]).json()["items"][0]["result"]["matches"] == []
    choose("user_2")
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalIdVote)) == 2
    assert _preview(app_client, [URL]).json()["items"][0]["result"]["matched_by"] == "external_id"


@pytest.mark.parametrize("ref", [
    {}, {"provider": "google", "external_id": "google:1"}, {"provider": "naver"},
    {"external_id": "naver:1"}, {**REF, "external_id": ""}, {**REF, "external_id": "1" * 101},
    {**REF, "external_id": 123}, {**REF, "extra": True}, [], "naver:1",
])
def test_invalid_link_ref_is_rejected_per_item(app_client, ref):
    body = {**KALGUKSU, "link_ref": ref}
    assert app_client.post("/maps/map_1/pins", json=body, cookies=_auth()).status_code == 422
    results = _bulk(app_client, [body, CAFE]).json()["results"]
    assert [r["status"] for r in results] == ["rejected", "created"]
    assert results[0]["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("ref", [
    {**REF, "external_id": "not-a-number"}, {**REF, "external_id": "kakao:123"},
])
def test_bad_number_format_does_not_block_pin(app_client, db_session, real_number_table, ref):
    response = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "link_ref": ref}, cookies=_auth())
    assert response.status_code == 201
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalId)) == 0


@pytest.mark.parametrize("failure", ["sql", "flush", "exception"])
@pytest.mark.parametrize("bulk", [False, True])
def test_record_failure_keeps_pin_events_and_session_usable(app_client, db_session, monkeypatch, caplog, bulk, failure):
    seen = []
    secret_hash = places_api.voter_hash("user_1")

    def fail(provider, external_id, place_id, *, source, voter_hash, db):
        seen.append((provider, external_id, place_id, source, voter_hash, db))
        if failure == "sql":
            db.execute(text("SELECT 1 / 0"))
        elif failure == "flush":
            db.add(PlaceExternalId(provider=provider, external_id=external_id, place_id=None, source=source))
        else:
            raise RuntimeError(f"{external_id} 비밀상호 비밀주소 {voter_hash}")

    monkeypatch.setattr(places_api, "record_external_id", fail)
    body = {**KALGUKSU, "link_ref": REF}
    with caplog.at_level(logging.WARNING, logger="pingo.pins.service"):
        if bulk:
            results = _bulk(app_client, [CAFE, body]).json()["results"]
            assert [r["status"] for r in results] == ["created", "created"]
        else:
            assert app_client.post("/maps/map_1/pins", json=body, cookies=_auth()).status_code == 201
    assert db_session.scalar(select(func.count()).select_from(PinRow)) == (2 if bulk else 1)
    assert len(_events(db_session, type="pin.created")) == (2 if bulk else 1)
    assert db_session.execute(text("SELECT 1")).scalar() == 1
    assert seen[0][0:2] == ("naver", REF["external_id"])
    assert seen[0][3:] == ("user", secret_hash, db_session)
    assert all(secret not in caplog.text for secret in (URL, REF["external_id"], secret_hash, "비밀상호", "비밀주소"))


def test_number_record_is_rolled_back_with_outer_pin_transaction(app_client, db_session, real_number_table):
    from authz.core import Principal
    from pins import service
    from pins.schemas import PinCreateSearch

    with db_session.begin_nested() as tx:
        service.create_pin(db_session, "map_1", Principal(user_id="user_1", map_id="map_1", role="member"), PinCreateSearch(**KALGUKSU, link_ref=REF))
        assert db_session.scalar(select(func.count()).select_from(PlaceExternalIdVote)) == 1
        tx.rollback()
    assert db_session.scalar(select(func.count()).select_from(PinRow)) == 0
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalIdVote)) == 0

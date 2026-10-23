"""places.api.get_ad_places — 추천 탭 광고용 읽기(docs/ads.md 5·6절, #645). 실제 PostGIS가 필요하다."""

import uuid

import pytest
from geoalchemy2 import Geography
from sqlalchemy import func

from places import api
from places.models import Place

CENTER = (37.5, 127.0)
RADIUS_M = 5000
ALL = ["음식점", "카페", "관광지"]


def _place(db, source_id, distance, *, name="광고 카페", category="카페", status="open",
           kakao_place_id=None, kakao_place_url=None, address="서울 성동구 1"):
    """CENTER에서 북쪽으로 distance(m) — DB(타원체)가 재는 거리와 정확히 일치한다."""
    point = func.ST_Project(
        func.ST_SetSRID(func.ST_MakePoint(CENTER[1], CENTER[0]), 4326).cast(Geography()), distance, func.radians(0))
    row = Place(source="permit", source_id=source_id, name=name, category=category, geom=point, status=status,
                address=address, kakao_place_id=kakao_place_id, kakao_place_url=kakao_place_url)
    db.add(row)
    db.flush()
    return str(row.id)


def _ids(rows):
    return {r["id"] for r in rows}


def _get(db, place_ids, *, center=CENTER, radius_m=RADIUS_M, categories=ALL):
    return api.get_ad_places(db, place_ids=place_ids, center=center, radius_m=radius_m, categories=categories)


def test_returns_the_contract_fields(db_session):
    pid = _place(db_session, "a", 100, kakao_place_id="k1", kakao_place_url="http://place.map.kakao.com/k1")
    [row] = _get(db_session, [pid])
    assert set(row) == {"id", "name", "category", "address", "lat", "lng", "kakao_place_id", "kakao_place_url"}
    assert row["id"] == pid and row["name"] == "광고 카페" and row["category"] == "카페"
    assert row["address"] == "서울 성동구 1"
    assert row["kakao_place_id"] == "k1" and row["kakao_place_url"] == "http://place.map.kakao.com/k1"
    assert (row["lat"], row["lng"]) == pytest.approx((CENTER[0] + 100 / 111_000, CENTER[1]), abs=1e-4)


def test_closed_place_is_excluded(db_session):
    open_ = _place(db_session, "open", 100)
    closed = _place(db_session, "closed", 100, status="closed")
    assert _ids(_get(db_session, [open_, closed])) == {open_}


def test_outside_radius_is_excluded(db_session):
    inside = _place(db_session, "in", 4999.9)
    outside = _place(db_session, "out", 5000.1)
    assert _ids(_get(db_session, [inside, outside])) == {inside}


def test_category_filter(db_session):
    cafe = _place(db_session, "cafe", 100, category="카페")
    food = _place(db_session, "food", 100, category="음식점")
    spot = _place(db_session, "spot", 100, category="관광지")
    assert _ids(_get(db_session, [cafe, food, spot], categories=["카페"])) == {cafe}
    assert _ids(_get(db_session, [cafe, food, spot], categories=["음식점", "관광지"])) == {food, spot}
    assert _get(db_session, [cafe, food, spot], categories=[]) == []


def test_unknown_and_malformed_ids_are_ignored(db_session):
    pid = _place(db_session, "a", 100)
    assert _ids(_get(db_session, [str(uuid.uuid4()), "not-a-uuid", pid])) == {pid}
    assert _get(db_session, []) == []


def test_only_given_ids_are_returned(db_session):
    asked = _place(db_session, "asked", 100)
    _place(db_session, "not-asked", 100)
    assert _ids(_get(db_session, [asked])) == {asked}


def test_null_kakao_fields_and_address_pass_through(db_session):
    pid = _place(db_session, "a", 100, address=None)
    [row] = _get(db_session, [pid])
    assert row["address"] is None and row["kakao_place_id"] is None and row["kakao_place_url"] is None


def test_read_only(db_session):
    pid = _place(db_session, "a", 100)
    _get(db_session, [pid])
    assert not db_session.dirty and not db_session.new

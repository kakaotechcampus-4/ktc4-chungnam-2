"""places.api.search_own_by_name(#674) — 자체 DB 이름 부분 일치. 실제 PostgreSQL+PostGIS."""

import pytest
from sqlalchemy import select

from places import api, ingest, repository
from places.models import Place


def _seed(db):
    def row(sid, name, category, address="서울특별시 종로구 1", status="open", source="permit"):
        return ingest.PlaceRow(source, sid, name, category, address, None, 37.57, 126.98, status)

    repository.upsert_places(db, [
        row("1", "경복궁", "관광지", source="tourapi"), row("2", "Gyeongbok Cafe", "카페"), row("3", "경복궁 앞 칼국수", "음식점"),
        row("4", "100% 순두부", "음식점"), row("5", "a_b 식당", "음식점"), row("6", "ab 식당", "음식점"),
    ])
    repository.upsert_places(db, [row("7", "경복궁역 분식", "음식점")])
    place = db.execute(select(Place).where(Place.source_id == "7")).scalar_one()
    place.status = "closed"   # 폐업 행은 새로 안 넣으므로 열어 둔 뒤 닫는다
    db.flush()


def _names(found):
    return [f["name"] for f in found]


def test_partial_match_returns_the_documented_shape_sorted_by_name(db_session):
    _seed(db_session)
    found = api.search_own_by_name(db_session, query="경복궁")
    assert _names(found) == sorted(_names(found)) == ["경복궁", "경복궁 앞 칼국수", "경복궁역 분식"]
    assert set(found[0]) == {"id", "name", "address", "category", "status"}
    assert found[0]["category"] == "관광지" and found[0]["status"] == "open" and found[0]["address"] == "서울특별시 종로구 1"
    assert found[0]["id"] == str(db_session.execute(select(Place.id).where(Place.source_id == "1")).scalar_one())


def test_case_insensitive(db_session):
    _seed(db_session)
    assert _names(api.search_own_by_name(db_session, query="GYEONGBOK")) == ["Gyeongbok Cafe"]


def test_closed_places_are_included_regardless_of_status(db_session):
    _seed(db_session)
    found = api.search_own_by_name(db_session, query="분식")
    assert [(f["name"], f["status"]) for f in found] == [("경복궁역 분식", "closed")]


def test_category_filter(db_session):
    _seed(db_session)
    assert _names(api.search_own_by_name(db_session, query="경복궁", category="음식점")) == ["경복궁 앞 칼국수", "경복궁역 분식"]
    assert api.search_own_by_name(db_session, query="경복궁", category="카페") == []


def test_limit_applies_after_name_ordering(db_session):
    _seed(db_session)
    assert _names(api.search_own_by_name(db_session, query="경복궁", limit=2)) == ["경복궁", "경복궁 앞 칼국수"]
    assert api.search_own_by_name(db_session, query="경복궁", limit=0) == []


def test_default_limit_is_20(db_session):
    repository.upsert_places(db_session, [ingest.PlaceRow("permit", f"x{i:02d}", f"공통 {i:02d}", "카페", None, None, 37.5, 127.0, "open") for i in range(25)])
    assert len(api.search_own_by_name(db_session, query="공통")) == 20


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_returns_nothing(db_session, query):
    _seed(db_session)
    assert api.search_own_by_name(db_session, query=query) == []


def test_like_wildcards_are_searched_literally(db_session):
    _seed(db_session)
    assert _names(api.search_own_by_name(db_session, query="%")) == ["100% 순두부"]
    assert _names(api.search_own_by_name(db_session, query="a_b")) == ["a_b 식당"]   # ab 식당은 걸리지 않는다


def test_no_match_and_read_only(db_session):
    _seed(db_session)
    before = db_session.execute(select(Place.updated_at).order_by(Place.id)).scalars().all()
    assert api.search_own_by_name(db_session, query="없는이름") == []
    assert db_session.execute(select(Place.updated_at).order_by(Place.id)).scalars().all() == before
    assert not db_session.dirty and not db_session.new

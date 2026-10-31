"""장소 검색 정렬(#835) — 지역 구역(30km) 먼저, 구역 안에서 이름 일치 정도 → 가까운 순 → 정예. 실제 PostgreSQL+PostGIS."""

import main  # noqa: F401 — 순환 import 방지
import pytest
from sqlalchemy import text

from places import api, ingest, repository
from places.models import Place

SEOUL = (37.5665, 126.9780)


def _add(db, sid, name, lat, lng, *, address="서울특별시 종로구 사직로 1", category="음식점", curated=False):
    repository.upsert_places(db, [ingest.PlaceRow("permit", sid, name, category, address, None, lat, lng, "open")])
    if curated:
        db.execute(Place.__table__.update().where(Place.source_id == sid).values(curated=True))
    db.flush()


def _names(db, q, near=SEOUL, limit=10):
    return [h.result.place_name for h in api.search_own_for_query(q, near, limit, db=db)]


def test_near_non_curated_beats_far_curated(db_session):
    _add(db_session, "a", "대전 맛집", 36.35, 127.38, curated=True)    # 140km
    _add(db_session, "b", "서울 맛집", 37.5700, 126.9800)
    assert _names(db_session, "맛집") == ["서울 맛집", "대전 맛집"]


def test_exact_before_prefix_before_substring_before_address(db_session):
    _add(db_session, "a", "스타벅스 경복궁점", 37.5760, 126.9770)   # 앞부분 일치(가까움)
    _add(db_session, "b", "이디야 경복궁", 37.5761, 126.9771)        # 부분 일치(더 가까움)
    _add(db_session, "c", "경복궁", 37.5800, 126.9800)               # 완전 일치(더 멂)
    _add(db_session, "d", "경복궁 앞 분식", 37.5770, 126.9772)       # 앞부분 일치
    _add(db_session, "e", "다른 가게", 37.5766, 126.9773, address="서울 종로구 경복궁길 1")   # 주소만
    names = _names(db_session, "경복궁")
    assert names[0] == "경복궁"
    assert names.index("경복궁 앞 분식") < names.index("이디야 경복궁") < names.index("다른 가게")


def test_exact_match_ignores_parentheses_and_symbols(db_session):
    _add(db_session, "a", "국립중앙박물관(본관)", 37.5239, 126.9803)
    _add(db_session, "b", "이디야 국립중앙박물관점", 37.5240, 126.9804)
    assert _names(db_session, "국립중앙박물관")[0] == "국립중앙박물관(본관)"


def test_within_the_same_level_nearer_first_then_curated(db_session):
    _add(db_session, "a", "맛집 먼", 37.60, 126.98, curated=True)
    _add(db_session, "b", "맛집 가까", 37.5670, 126.9781)
    assert _names(db_session, "맛집") == ["맛집 가까", "맛집 먼"]


def test_curated_wins_only_on_equal_distance(db_session):
    _add(db_session, "a", "맛집 가", 37.5700, 126.9800)
    _add(db_session, "b", "맛집 나", 37.5700, 126.9800, curated=True)
    assert _names(db_session, "맛집") == ["맛집 나", "맛집 가"]


def test_far_zone_fills_only_when_region_is_short(db_session):
    _add(db_session, "a", "맛집 서울", 37.5700, 126.9800)
    _add(db_session, "b", "맛집 부산", 35.17, 129.07)
    assert _names(db_session, "맛집", limit=1) == ["맛집 서울"]
    assert _names(db_session, "맛집", limit=5) == ["맛집 서울", "맛집 부산"]
    assert _names(db_session, "맛집", near=(35.18, 129.08), limit=5) == ["맛집 부산", "맛집 서울"]


def test_far_zone_alone_can_fill_the_limit(db_session):
    # 지역 구역이 비면 먼 구역만으로 채운다
    for i in range(3):
        _add(db_session, f"f{i}", f"맛집 먼{i}", 35.17 + i * 0.01, 129.07)
    assert len(_names(db_session, "맛집", limit=3)) == 3


def test_without_coordinates_level_then_curated_then_name(db_session):
    _add(db_session, "a", "가 맛집 정예", 37.5, 127.0, curated=True)
    _add(db_session, "b", "맛집", 37.6, 127.1)
    _add(db_session, "c", "나 맛집", 37.7, 127.2)
    assert _names(db_session, "맛집", near=None) == ["맛집", "가 맛집 정예", "나 맛집"]


def test_two_char_query_uses_the_geometry_index_in_the_region_zone(db_session):
    _add(db_session, "a", "안국 식당", 37.5760, 126.9850)
    # 실행 계획: 지역 구역 쿼리가 places_geom 인덱스를 쓴다(작은 테이블이라 플래너가 순차 훑기를 고를 수 있어 강제한다)
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(db_session.execute(text(
        "EXPLAIN SELECT id FROM places WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(126.978, 37.5665), 4326)::geography, 30000) AND name ILIKE '%안국%'"
    )).scalars())
    assert "idx_places_geom" in plan, plan

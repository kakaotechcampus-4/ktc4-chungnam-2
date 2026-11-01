"""장소 검색의 계층별 조회(#835 속도 후속) — 계약의 순서는 그대로, 비싼 계층은 앞 계층이 모자랄 때만. 실제 PostgreSQL+PostGIS."""

import main  # noqa: F401 — 순환 import 방지
import pytest
from sqlalchemy import select, text

from places import api, ingest, matching, repository
from places.models import Place

SEOUL = (37.5665, 126.9780)


def _add(db, sid, name, lat, lng, *, address="서울특별시 종로구 사직로 1", curated=False):
    repository.upsert_places(db, [ingest.PlaceRow("permit", sid, name, "음식점", address, None, lat, lng, "open")])
    if curated:
        db.execute(Place.__table__.update().where(Place.source_id == sid).values(curated=True))
    db.flush()


def _names(db, q, near=SEOUL, limit=10):
    return [h.result.place_name for h in api.search_own_for_query(q, near, limit, db=db)]


@pytest.fixture()
def calls(monkeypatch):
    seen = []
    real = repository.search_open_by_query

    def spy(db, query, near, limit, offset=0, *, tier, band=(None, None), skip_part_within=None):
        seen.append((tier, band))
        return real(db, query, near, limit, offset, tier=tier, band=band, skip_part_within=skip_part_within)

    monkeypatch.setattr(repository, "search_open_by_query", spy)
    return seen


# ---- name_norm: SQL 정규형이 matching.normalize_name과 같다 ----

@pytest.mark.parametrize("name", ["스타벅스 경복궁점", "국립중앙박물관(본관)", "Café  A&B", "오레노 라멘안국", "[본점] 맛-집", "（주）가게 (2호점)", "ＡＢＣ 카페", "가게!!!", "()"])
def test_name_norm_column_equals_python_normalize_name(db_session, name):
    _add(db_session, "n", name, *SEOUL)
    assert db_session.scalar(select(Place.name_norm)) == matching.normalize_name(name)


# ---- 계층 전환 ----

def test_prefix_tier_alone_fills_the_limit_without_reading_costly_tiers(db_session, calls):
    for i in range(3):
        _add(db_session, f"a{i}", f"맛집 {i}", 37.57 + i * 0.001, 126.98)
    _add(db_session, "z", "이 집은 맛집", 37.5701, 126.98)   # 부분 일치 — 읽을 필요가 없다
    assert len(_names(db_session, "맛집", limit=3)) == 3
    assert calls == [(repository.TIER_NAME_PREFIX, (None, repository.REGION_RADIUS_M))]


def test_costly_tiers_start_with_the_close_band_and_widen_only_when_short(db_session, calls):
    _add(db_session, "a", "이 집은 맛집", 37.5700, 126.98)    # 부분 일치, 약 0.5km
    _add(db_session, "b", "저 집은 맛집", 37.6500, 126.98)    # 부분 일치, 약 9km
    assert _names(db_session, "맛집", limit=1) == ["이 집은 맛집"]
    assert [t for t, _ in calls] == [repository.TIER_NAME_PREFIX, repository.TIER_NAME_PART]   # 전체 훑기(계층 3)까지 가지 않는다
    calls.clear()
    assert _names(db_session, "맛집", limit=2) == ["이 집은 맛집", "저 집은 맛집"]
    assert (repository.TIER_REST, (None, repository.REGION_RADIUS_M)) in calls


def test_order_is_tier_first_even_when_the_lower_tier_is_nearer(db_session):
    _add(db_session, "a", "다른 가게", 37.5666, 126.9781, address="서울 종로구 맛집길 1")   # 주소 일치, 아주 가까움
    _add(db_session, "b", "이 집은 맛집", 37.6500, 126.98)                                  # 부분 일치, 약 9km
    _add(db_session, "c", "맛집 본점", 37.6900, 127.0)                                       # 앞부분 일치, 약 14km
    assert _names(db_session, "맛집") == ["맛집 본점", "이 집은 맛집", "다른 가게"]


def test_region_zone_tiers_all_come_before_the_far_zone(db_session):
    _add(db_session, "a", "다른 가게", 37.5666, 126.9781, address="서울 종로구 맛집길 1")   # 지역 구역의 주소 일치
    _add(db_session, "b", "맛집", 35.17, 129.07)                                              # 먼 구역의 완전 일치
    assert _names(db_session, "맛집") == ["다른 가게", "맛집"]


def test_exact_before_prefix_inside_the_prefix_tier_and_spaces_ignored(db_session):
    _add(db_session, "a", "국립 중앙박물관 카페", 37.5239, 126.9803)
    _add(db_session, "b", "국립중앙박물관", 37.5300, 126.9900)
    assert _names(db_session, "국립중앙박물관") == ["국립중앙박물관", "국립 중앙박물관 카페"]   # 공백이 든 이름도 앞부분 일치로 걸린다


def test_without_coordinates_tiers_in_order_then_curated_then_name(db_session, calls):
    _add(db_session, "a", "이 집은 맛집", 37.5, 127.0, curated=True)
    _add(db_session, "b", "맛집 나", 37.6, 127.1)
    _add(db_session, "c", "맛집 가", 37.7, 127.2, curated=True)
    assert _names(db_session, "맛집", near=None) == ["맛집 가", "맛집 나", "이 집은 맛집"]
    assert calls[0] == (repository.TIER_NAME_PREFIX, (None, None))


def test_symbol_only_query_skips_the_prefix_tier(db_session):
    _add(db_session, "a", "가게(!)", 37.57, 126.98)
    assert _names(db_session, "(!)") == ["가게(!)"]


# ---- 실행 계획 ----

def test_prefix_tier_uses_the_name_norm_index_even_for_two_char_queries(db_session):
    _add(db_session, "a", "안국 식당", 37.5760, 126.9850)
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(db_session.execute(text("EXPLAIN SELECT id FROM places WHERE name_norm LIKE '안국%'")).scalars())
    assert "idx_places_name_norm" in plan, plan


def test_close_part_matches_are_not_read_twice_when_the_ladder_widens(db_session):
    _add(db_session, "a", "이 집은 맛집", 37.5700, 126.98)                                       # 부분 일치, 3km 안(계층 2로 읽는다)
    _add(db_session, "b", "저 집은 맛집", 37.6500, 126.98)                                       # 부분 일치, 3km 밖
    _add(db_session, "c", "다른 가게", 37.5666, 126.9781, address="서울 종로구 맛집길 1")         # 주소만, 3km 안
    assert _names(db_session, "맛집", limit=3) == ["이 집은 맛집", "저 집은 맛집", "다른 가게"]

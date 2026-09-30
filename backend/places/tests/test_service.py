"""PlaceService — 캐시 동작, resolve 규칙, get_raw_facts 보완 호출 횟수."""

import pytest

from common.errors import AppError
from places.cache import TTLCache
from places.schemas import Area
from places.service import PlaceService
from places.sources.base import ENRICHABLE_FIELDS, RawPlace
from places.tests.test_fallback import FakeSource, place


def service(sources, ttl=600):
    cache: TTLCache[RawPlace] = TTLCache(ttl)
    return PlaceService(sources, cache)


AREA = [Area(lat=37.5, lng=127.0, radius_m=500)]


def test_search_returns_only_refs_and_dedupes_across_areas():
    k = FakeSource("kakao", nearby=[place(source_id="1"), place(source_id="2")])
    refs = service([k]).search_nearby("음식점", AREA + AREA)
    assert [r.place_id for r in refs] == ["kakao:1", "kakao:2"]
    assert not hasattr(refs[0], "name")   # 밖으로는 식별자·좌표만 나간다


def test_raw_facts_returns_layer1_and_only_non_empty_values():
    k = FakeSource("kakao", nearby=[place(address="서울", phone="02-1")])
    svc = service([k])
    svc.search_nearby("음식점", AREA)
    facts = svc.get_raw_facts("kakao:1")
    assert facts == {"name": "가게", "category": "음식점", "address": "서울", "phone": "02-1"}


def test_raw_facts_unknown_place_is_empty():
    assert service([]).get_raw_facts("kakao:404") == {}


def test_raw_facts_enrichment_is_attempted_once_per_place():
    g = FakeSource("google", provides=ENRICHABLE_FIELDS, fills={})   # 구글이 못 찾는 장소
    svc = service([FakeSource("kakao", nearby=[place()]), g])
    svc.search_nearby("음식점", AREA)
    svc.get_raw_facts("kakao:1")
    svc.get_raw_facts("kakao:1")
    assert len(g.fill_asks) == 1   # 못 채웠다고 과금 호출을 반복하지 않는다


def test_raw_facts_expose_enriched_price_level_but_no_price_numbers():
    g = FakeSource("google", provides=ENRICHABLE_FIELDS, fills={"price_level": "EXPENSIVE", "rating": 4.2, "rating_count": 9})
    svc = service([FakeSource("kakao", nearby=[place()]), g])
    svc.search_nearby("음식점", AREA)
    facts = svc.get_raw_facts("kakao:1")
    assert facts["price_level"] == "EXPENSIVE" and facts["rating"] == 4.2
    assert not any("price_range" in k or k == "price" for k in facts)


def test_cache_disabled_keeps_nothing():
    svc = service([FakeSource("kakao", nearby=[place()])], ttl=0)
    assert len(svc.search_nearby("음식점", AREA)) == 1
    assert svc.get_raw_facts("kakao:1") == {}


def test_cache_entries_expire():
    now = [0.0]
    cache: TTLCache[str] = TTLCache(10, clock=lambda: now[0])
    cache.put("a", "v")
    assert cache.get("a") == "v"
    now[0] = 10.0
    assert cache.get("a") is None


def test_cache_evicts_when_full():
    cache: TTLCache[int] = TTLCache(100, max_size=2)
    for i in range(3):
        cache.put(str(i), i)
    assert sum(cache.get(str(i)) is not None for i in range(3)) == 2


# ---- resolve ----

def test_resolve_search_passes_coords_through():
    r = service([]).resolve("search", "kakao:1", 37.1, 127.1)
    assert (r.place_id, r.lat, r.lng) == ("kakao:1", 37.1, 127.1)


def test_resolve_search_fills_coords_from_recent_search():
    svc = service([FakeSource("kakao", nearby=[place(lat=37.7, lng=127.7)])])
    svc.search_nearby("음식점", AREA)
    r = svc.resolve("search", "kakao:1", None, None)
    assert (r.lat, r.lng) == (37.7, 127.7)


def test_resolve_search_without_coords_or_cache_is_422():
    with pytest.raises(AppError) as e:
        service([]).resolve("search", "kakao:404", None, None)
    assert e.value.code == "VALIDATION_ERROR"


def test_resolve_search_requires_place_id():
    with pytest.raises(AppError):
        service([]).resolve("search", None, 1.0, 2.0)


def test_resolve_coordinate_synthesizes_id_like_dev_gateway():
    r = service([]).resolve("coordinate", None, 37.5, 127.0)
    assert r.place_id == "coord:37.500000,127.000000"


def test_resolve_coordinate_requires_coords():
    with pytest.raises(AppError):
        service([]).resolve("coordinate", None, None, None)

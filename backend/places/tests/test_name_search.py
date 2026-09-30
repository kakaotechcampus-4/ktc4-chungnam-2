"""이름 검색(#180) — 카카오 keyword 요청 모양, 폴백/503, 호출 상한, 캐시 좌표 대조, dev 샘플."""

import pytest

from common.errors import AppError
from places.cache import TTLCache
from places.fallback import search_by_name_with_fallback
from places.http import SourceError
from places.ratelimit import SlidingWindowLimiter
from places.samples import SAMPLE_PLACES, search_samples
from places.service import PlaceService
from places.sources.kakao import KakaoPlaceSource
from places.tests.helpers import KAKAO_DOC, json_response, make_http
from places.tests.test_fallback import FakeSource, place


# ---- 카카오 keyword ----

def test_kakao_name_search_with_coords_sorts_by_distance():
    http, _, seen = make_http(json_response({"documents": [KAKAO_DOC], "meta": {}}))
    found = KakaoPlaceSource(http, "KEY").search_by_name(query="칼국수", lat=37.5, lng=127.0, limit=10)
    p = seen[0].url.params
    assert seen[0].url.path.endswith("/keyword.json")
    assert p["query"] == "칼국수" and p["sort"] == "distance" and p["x"] == "127.0" and p["y"] == "37.5"
    assert "KEY" not in str(seen[0].url)
    assert found[0].name == "성수 칼국수" and found[0].category == "음식점"


def test_kakao_name_search_without_coords_is_relevance_order():
    http, _, seen = make_http(json_response({"documents": []}))
    assert KakaoPlaceSource(http, "k").search_by_name(query="a", lat=None, lng=None, limit=5) == []
    p = seen[0].url.params
    assert "sort" not in p and "x" not in p and p["size"] == "5"


def test_kakao_name_search_respects_limit_and_page_size_cap():
    docs = [{**KAKAO_DOC, "id": str(i)} for i in range(15)]
    http, _, _ = make_http(json_response({"documents": docs}))
    assert len(KakaoPlaceSource(http, "k").search_by_name(query="a", lat=None, lng=None, limit=3)) == 3
    http, _, seen = make_http(json_response({"documents": []}))
    KakaoPlaceSource(http, "k").search_by_name(query="a", lat=None, lng=None, limit=99)
    assert seen[0].url.params["size"] == "15"


def test_kakao_unknown_category_group_is_etc():
    http, _, _ = make_http(json_response({"documents": [{**KAKAO_DOC, "category_group_code": ""}]}))
    assert KakaoPlaceSource(http, "k").search_by_name(query="a", lat=None, lng=None, limit=5)[0].category == "기타"


# ---- 폴백 / 503 ----

class NamedFake(FakeSource):
    def __init__(self, name, *, result=None, fail=False, configured=True):
        super().__init__(name, configured=configured, fail=fail)
        self._result = result or []
        self.calls = 0

    def search_by_name(self, **_):
        self.calls += 1
        if self._fail:
            raise SourceError("down")
        return self._result


ARGS = dict(query="x", lat=None, lng=None, limit=5)


def test_zero_results_is_empty_list_not_error():
    assert search_by_name_with_fallback([NamedFake("kakao")], **ARGS) == []


def test_all_failing_raises():
    with pytest.raises(SourceError):
        search_by_name_with_fallback([NamedFake("kakao", fail=True)], **ARGS)


def test_missing_key_raises():
    with pytest.raises(SourceError):
        search_by_name_with_fallback([NamedFake("kakao", configured=False)], **ARGS)


def test_sources_without_name_search_are_ignored_and_none_left_raises():
    with pytest.raises(SourceError):
        search_by_name_with_fallback([FakeSource("naver")], **ARGS)


def test_failure_then_success_with_zero_results_is_empty_not_503():
    assert search_by_name_with_fallback([NamedFake("a", fail=True), NamedFake("b")], **ARGS) == []


def _svc(*sources, ttl=600):
    return PlaceService(sources, TTLCache(ttl))


def test_service_maps_to_search_result_and_caches():
    svc = _svc(NamedFake("kakao", result=[place(address="서울", place_url="http://p")]))
    [r] = svc.search_by_name("가게", None, 5)
    assert (r.place_id, r.place_name, r.category, r.address) == ("kakao:1", "가게", "음식점", "서울")
    assert r.place_source.provider == "kakao" and r.place_source.url == "http://p"
    assert svc.get_raw_facts("kakao:1")["name"] == "가게"


def test_service_truncates_long_name_to_pin_limit():
    [r] = _svc(NamedFake("kakao", result=[place(name="가" * 150)])).search_by_name("가", None, 5)
    assert len(r.place_name) == 100


def test_service_all_failing_is_places_unavailable():
    with pytest.raises(AppError) as e:
        _svc(NamedFake("kakao", fail=True)).search_by_name("x", None, 5)
    assert (e.value.code, e.value.status) == ("PLACES_UNAVAILABLE", 503)


# ---- resolve: 캐시 좌표 대조 ----

def _cached_svc():
    svc = _svc(NamedFake("kakao", result=[place(lat=37.5, lng=127.0)]))
    svc.search_by_name("가게", None, 5)
    return svc


def test_resolve_rejects_echo_far_from_cached_coords():
    with pytest.raises(AppError) as e:
        _cached_svc().resolve("search", "kakao:1", 37.6, 127.0)   # 약 11km
    assert e.value.code == "VALIDATION_ERROR"


def test_resolve_accepts_echo_within_200m():
    assert _cached_svc().resolve("search", "kakao:1", 37.5005, 127.0).lat == 37.5005   # 약 55m


def test_resolve_uses_echo_when_cache_is_gone():
    assert _svc(ttl=0).resolve("search", "kakao:1", 10.0, 20.0).lat == 10.0


# ---- 호출 상한 ----

def test_limiter_blocks_after_limit_and_recovers_after_window():
    now = [0.0]
    lim = SlidingWindowLimiter(2, 60, clock=lambda: now[0])
    assert lim.allow("u") and lim.allow("u") and not lim.allow("u")
    assert lim.allow("other")            # 사용자별로 센다
    now[0] = 60.0
    assert lim.allow("u")


def test_limiter_zero_disables():
    lim = SlidingWindowLimiter(0)
    assert all(lim.allow("u") for _ in range(100))


# ---- dev 샘플 ----

def test_samples_are_the_five_mock_places():
    assert [p.name for p in SAMPLE_PLACES] == ["해운대 밀면", "해운대 바다 카페", "광안리 해변", "광안리 게스트하우스", "제주 흑돼지 거리"]


def test_samples_partial_match_sorted_by_distance_and_limited():
    assert [p.name for p in search_samples("해운대", None, None, 10)] == ["해운대 밀면", "해운대 바다 카페"]
    assert search_samples("해운대", 35.1587, 129.1604, 10)[0].name == "해운대 바다 카페"
    assert len(search_samples("광안리", None, None, 1)) == 1
    assert search_samples("없는곳", None, None, 10) == []

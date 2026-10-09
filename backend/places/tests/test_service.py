"""PlaceService — 지도 API 응답은 어디에도 남지 않는다(#188). resolve는 echo 값을 그대로 쓴다."""

import pytest

from common.errors import AppError
from places.schemas import Area
from places.service import PlaceService
from places.tests.test_fallback import FakeSource, place
from places.tests.test_name_search import NamedFake

AREA = [Area(lat=37.5, lng=127.0, radius_m=500)]
MARK = dict(name="카카오전용가게ZZ", phone="02-000-KAKAO", address="카카오주소ZZ", place_url="http://kakao.example/zz")


def _svc(*sources):
    return PlaceService(sources)


def test_search_returns_only_refs_and_dedupes_across_areas():
    k = FakeSource("kakao", nearby=[place(source_id="1"), place(source_id="2")])
    refs = _svc(k).search_nearby("음식점", AREA + AREA)
    assert [r.place_id for r in refs] == ["kakao:1", "kakao:2"]
    assert not hasattr(refs[0], "name")   # 밖으로는 식별자·좌표만 나간다


def test_service_keeps_no_state_beyond_its_sources():
    svc = _svc(NamedFake("kakao", result=[place(**MARK)]))
    svc.search_by_name("가게", None, 5)
    svc.search_nearby("음식점", AREA)
    assert set(vars(svc)) == {"_sources"}   # 캐시·저장소 필드가 없다


def test_raw_facts_is_empty_even_right_after_a_search():
    k = FakeSource("kakao", nearby=[place(**MARK)])
    svc = _svc(k)
    svc.search_nearby("음식점", AREA)
    assert svc.get_raw_facts("kakao:1") == {}


def test_raw_facts_is_empty_after_name_search_too():
    svc = _svc(NamedFake("kakao", result=[place(**MARK)]))
    svc.search_by_name("가게", None, 5)
    assert svc.get_raw_facts("kakao:1") == {}


def test_raw_facts_never_calls_any_source_to_enrich():
    g = FakeSource("naver", provides={"rating"}, nearby=[place("naver")])
    svc = _svc(FakeSource("kakao", nearby=[place(**MARK)]), g)
    svc.search_nearby("음식점", AREA)
    svc.get_raw_facts("kakao:1")
    assert g.fill_asks == [] and g.nearby_calls == 0


# ---- resolve: 요청에 실려 온 값을 그대로 (#191 전 임시 동작) ----

def test_resolve_search_passes_echo_coords_through():
    r = _svc().resolve("search", "kakao:1", 37.1, 127.1)
    assert (r.place_id, r.lat, r.lng) == ("kakao:1", 37.1, 127.1)


def test_resolve_search_does_not_use_or_compare_with_a_previous_search():
    svc = _svc(NamedFake("kakao", result=[place(lat=37.5, lng=127.0)]))
    svc.search_by_name("가게", None, 5)
    r = svc.resolve("search", "kakao:1", 10.0, 20.0)   # 검색 결과와 완전히 다른 좌표도 echo 그대로
    assert (r.lat, r.lng) == (10.0, 20.0)


def test_resolve_search_without_coords_is_422_even_if_it_was_just_searched():
    svc = _svc(NamedFake("kakao", result=[place()]))
    svc.search_by_name("가게", None, 5)
    with pytest.raises(AppError) as e:
        svc.resolve("search", "kakao:1", None, None)
    assert e.value.code == "VALIDATION_ERROR"


def test_resolve_search_requires_place_id():
    with pytest.raises(AppError):
        _svc().resolve("search", None, 1.0, 2.0)


def test_resolve_coordinate_synthesizes_id_like_dev_gateway():
    assert _svc().resolve("coordinate", None, 37.5, 127.0).place_id == "coord:37.500000,127.000000"


def test_resolve_coordinate_requires_coords():
    with pytest.raises(AppError):
        _svc().resolve("coordinate", None, None, None)

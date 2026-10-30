"""PlaceService — 지도 API 응답은 어디에도 남지 않는다(#188)."""

from places.service import PlaceService
from places.tests.test_fallback import place
from places.tests.test_name_search import NamedFake

MARK = dict(name="카카오전용가게ZZ", phone="02-000-KAKAO", address="카카오주소ZZ", place_url="http://kakao.example/zz")


def _svc(*sources):
    return PlaceService(sources)


def test_service_keeps_no_state_beyond_its_sources():
    svc = _svc(NamedFake("kakao", result=[place(**MARK)]))
    svc.search_by_name("가게", None, 5)
    assert set(vars(svc)) == {"_sources"}   # 캐시·저장소 필드가 없다


def test_live_kakao_functions_that_nobody_calls_are_gone():
    """#773 — 카카오 실시간 후보 풀·원자료·echo 좌표 경로는 지웠다. 장소 후보는 자체 DB(search_nearby_own)에서만 온다."""
    from places import api

    for name in ("search_nearby", "get_raw_facts", "resolve_place", "call_counts"):
        assert not hasattr(api, name), name
    for name in ("search_nearby", "get_raw_facts", "resolve"):
        assert not hasattr(PlaceService, name), name

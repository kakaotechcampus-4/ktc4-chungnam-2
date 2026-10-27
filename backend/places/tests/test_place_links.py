"""동네, 카카오맵 검색 링크, 장소 링크(#799) — 순수 함수. docs/constraints.md 「카카오맵 검색 링크」."""

from urllib.parse import unquote

import pytest

from places import api, core
from places.schemas import Area, PlaceInfo
from places.testing import FakePlaces, _Row


@pytest.mark.parametrize("address, expected", [
    ("대구광역시 중구 동성로8길 10-5 (삼덕동)", "중구 삼덕동"),                     # 광역시 구
    ("부산광역시 해운대구 해운대해변로 264 (우동)", "해운대구 우동"),
    ("서울특별시 성동구 성수이로 10 (성수동2가)", "성동구 성수동2가"),               # 숫자+가 법정동
    ("강원특별자치도 춘천시 중앙로 1 (조운동)", "춘천시 조운동"),                     # 시
    ("강원특별자치도 양양군 양양읍 남문리 1", "양양군"),                              # 군, 괄호 없음
    ("경기도 수원시 팔달구 효원로 1 (인계동)", "팔달구 인계동"),                      # 일반구가 있는 시는 구까지
    ("세종특별자치시 한누리대로 2130 (보람동)", "세종특별자치시 보람동"),             # 구가 없는 곳
    ("부산광역시 해운대구 해운대해변로 264 (1층, 우동)", "해운대구 우동"),            # 괄호 안 건물 정보는 거른다
    ("서울특별시 성동구 왕십리로 1 (성수동1가, 성수아파트)", "성동구 성수동1가"),
    ("서울특별시 성동구 왕십리로 1 (101동)", "성동구"),                               # 아파트 동은 법정동이 아니다
    ("서울 성동구 성수이로 10", "성동구"),                                             # 줄인 시·도
    ("성동구 성수이로 10 (성수동2가)", "성동구 성수동2가"),                           # 시·도 없음
])
def test_neighborhood_cuts_sigungu_and_dong(address, expected):
    assert core.neighborhood(address) == expected


@pytest.mark.parametrize("address", [None, "", "   ", "어딘가 123"])
def test_neighborhood_is_none_without_address(address):
    assert core.neighborhood(address) is None


def test_kakao_search_url_encodes_whole_query():
    url = core.kakao_search_url("춘천 한식 & 술집/2")
    assert url.startswith("https://map.kakao.com/link/search/")
    tail = url.removeprefix("https://map.kakao.com/link/search/")
    assert " " not in tail and "&" not in tail and "/" not in tail
    assert unquote(tail) == "춘천 한식 & 술집/2"
    assert api.kakao_search_url("성수동 카페") == core.kakao_search_url("성수동 카페")


def test_place_link_prefers_recorded_kakao_url():
    info = PlaceInfo("p", "성수 칼국수", 1, 2, "음식점", "https://place.map.kakao.com/1", address="서울특별시 성동구 성수이로 10 (성수동2가)")
    assert api.place_link(info) == "https://place.map.kakao.com/1"


def test_place_link_searches_name_and_neighborhood():
    info = PlaceInfo("p", "성수 칼국수", 1, 2, "음식점", address="서울특별시 성동구 성수이로 10 (성수동2가)")
    assert api.place_link(info) == core.kakao_search_url("성수 칼국수 성동구 성수동2가")


def test_place_link_without_neighborhood_or_name():
    assert api.place_link(PlaceInfo("p", "성수 칼국수", 1, 2, "음식점")) == core.kakao_search_url("성수 칼국수")
    assert api.place_link(PlaceInfo("p", "성수 칼국수", 1, 2, "음식점", "")) == core.kakao_search_url("성수 칼국수")   # 빈 URL은 없는 것
    assert api.place_link(PlaceInfo("p", "  ", 1, 2, "음식점", address="부산광역시 해운대구 해운대해변로 264 (우동)")) is None


def test_fake_get_places_carries_address_for_place_link():
    fake = FakePlaces(rows=[_Row("a", "가게", 37.5, 127.0, "음식점", address="부산광역시 해운대구 해운대해변로 264 (우동)")])
    info = fake.get_places([fake.place_id("a")])[fake.place_id("a")]
    assert api.place_link(info) == core.kakao_search_url("가게 해운대구 우동")


def test_fake_count_curated_counts_open_curated_in_any_area():
    fake = FakePlaces(rows=[
        _Row("a", "정예", 37.5, 127.0, "음식점", curated=True),
        _Row("b", "커버리지", 37.5, 127.0, "음식점"),
        _Row("c", "폐업 정예", 37.5, 127.0, "음식점", status="closed", curated=True),
        _Row("d", "정예 카페", 37.5, 127.0, "카페", curated=True),
        _Row("e", "먼 정예", 37.6, 127.0, "음식점", curated=True),
    ])
    near = Area(37.5, 127.0, 300)
    assert fake.count_curated("음식점", [near]) == 1
    assert fake.count_curated("음식점", [near, near]) == 1   # 원이 겹쳐도 한 번
    assert fake.count_curated("음식점", [near, Area(37.6, 127.0, 300)]) == 2
    assert fake.count_curated("음식점", []) == 0
    assert fake.count_curated("숙소", [near]) == 0

"""3개 어댑터 — 요청 모양(헤더·파라미터·FieldMask)과 응답 파싱. 네트워크 없음."""

import json

import httpx
import pytest

from places.http import SourceError
from places.sources.base import RawPlace
from places.sources.google import GooglePlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource
from places.tests.helpers import KAKAO_DOC, json_response, make_http

PLACE = RawPlace(source="kakao", source_id="111", name="성수 칼국수", lat=37.5445, lng=127.0561, category="음식점")


# ---- 카카오 ----

def test_kakao_category_search_parses_and_sends_key_in_header():
    http, _, seen = make_http(json_response({"documents": [KAKAO_DOC], "meta": {"is_end": True}}))
    found = KakaoPlaceSource(http, "REST-KEY").search_nearby(category="음식점", lat=37.54, lng=127.05, radius_m=500)
    assert [p.place_id for p in found] == ["kakao:111"]
    assert found[0].category == "음식점" and found[0].phone == "02-111-2222"
    assert found[0].address == "서울 성동구 아차산로 1"
    req = seen[0]
    assert req.headers["Authorization"] == "KakaoAK REST-KEY"
    assert req.url.params["category_group_code"] == "FD6"
    assert req.url.params["radius"] == "500" and req.url.params["x"] == "127.05"
    assert "REST-KEY" not in str(req.url)   # 키는 URL에 안 실린다


def test_kakao_clamps_radius_and_pages_until_end():
    pages = iter([{"documents": [KAKAO_DOC], "meta": {"is_end": False}},
                  {"documents": [{**KAKAO_DOC, "id": "222"}], "meta": {"is_end": False}}])
    http, _, seen = make_http(lambda r: httpx.Response(200, json=next(pages)))
    found = KakaoPlaceSource(http, "k", max_pages=2).search_nearby(category="카페", lat=1, lng=2, radius_m=99999)
    assert len(found) == 2 and len(seen) == 2          # max_pages에서 멈춘다
    assert seen[0].url.params["radius"] == "20000"


def test_kakao_skips_broken_documents():
    http, _, _ = make_http(json_response({"documents": [{"id": "1"}, KAKAO_DOC], "meta": {"is_end": True}}))
    assert len(KakaoPlaceSource(http, "k").search_nearby(category="음식점", lat=1, lng=2, radius_m=10)) == 1


def test_kakao_etc_category_makes_no_call():
    http, _, seen = make_http(json_response({}))
    assert KakaoPlaceSource(http, "k").search_nearby(category="기타", lat=1, lng=2, radius_m=10) == []
    assert seen == []


def test_kakao_not_configured_without_key():
    http, _, _ = make_http(json_response({}))
    assert not KakaoPlaceSource(http, "").is_configured()


# ---- 네이버 ----

NAVER_ITEM = {"title": "<b>성수</b> 칼국수", "category": "음식점>한식", "telephone": "02-333-4444",
              "address": "서울 성동구 성수동", "roadAddress": "서울 성동구 아차산로 1", "link": "http://x",
              "mapx": "1270561000", "mapy": "375445000"}


def test_naver_parses_scaled_coords_and_strips_tags():
    http, _, seen = make_http(json_response({"items": [NAVER_ITEM]}))
    found = NaverPlaceSource(http, "id", "secret").search_nearby(category="음식점", lat=37.5445, lng=127.0561, radius_m=500)
    assert found[0].name == "성수 칼국수"
    assert found[0].lat == pytest.approx(37.5445) and found[0].lng == pytest.approx(127.0561)
    assert found[0].source == "naver" and found[0].source_id   # id가 없어서 합성한다
    assert seen[0].headers["X-Naver-Client-Id"] == "id" and seen[0].headers["X-Naver-Client-Secret"] == "secret"


def test_naver_filters_by_radius():
    http, _, _ = make_http(json_response({"items": [NAVER_ITEM]}))
    assert NaverPlaceSource(http, "i", "s").search_nearby(category="음식점", lat=35.0, lng=129.0, radius_m=500) == []


def test_naver_needs_both_credentials():
    http, _, _ = make_http(json_response({}))
    assert not NaverPlaceSource(http, "id", "").is_configured()


# ---- 구글 ----

GOOGLE_PLACE = {"id": "ChIJabc", "displayName": {"text": "성수 칼국수"},
                "location": {"latitude": 37.5445, "longitude": 127.0561}, "types": ["restaurant"],
                "formattedAddress": "서울", "googleMapsUri": "https://maps.google.com/?cid=1"}


def test_google_nearby_sends_field_mask_and_key_header():
    http, stats, seen = make_http(json_response({"places": [GOOGLE_PLACE]}))
    found = GooglePlaceSource(http, stats, "G-KEY").search_nearby(category="음식점", lat=37.5, lng=127.0, radius_m=800)
    assert found[0].place_id == "google:ChIJabc" and found[0].category == "음식점"
    req = seen[0]
    assert req.headers["X-Goog-Api-Key"] == "G-KEY"
    assert "places.rating" not in req.headers["X-Goog-FieldMask"]     # 검색 풀에는 과금 큰 필드를 안 붙인다
    assert json.loads(req.content)["includedTypes"] == ["restaurant"]


def test_google_fill_requests_only_wanted_fields_and_maps_values():
    body = {"places": [{**GOOGLE_PLACE, "rating": 4.4, "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE"}]}
    http, stats, seen = make_http(json_response(body))
    got = GooglePlaceSource(http, stats, "k").fill(PLACE, frozenset({"rating", "price_level"}))
    mask = seen[0].headers["X-Goog-FieldMask"]
    assert "places.rating" in mask and "places.priceLevel" in mask
    assert "regularOpeningHours" not in mask and "nationalPhoneNumber" not in mask
    assert got["rating"] == 4.4 and got["rating_count"] == 120 and got["price_level"] == "MODERATE"
    assert "priceRange" not in mask   # 가격 숫자는 요청하지 않는다


def test_google_fill_ignores_different_place():
    other = {**GOOGLE_PLACE, "displayName": {"text": "완전 다른 가게"}, "rating": 5.0}
    http, stats, _ = make_http(json_response({"places": [other]}))
    assert GooglePlaceSource(http, stats, "k").fill(PLACE, frozenset({"rating"})) == {}


def test_google_fill_with_nothing_it_provides_makes_no_call():
    http, stats, seen = make_http(json_response({}))
    assert GooglePlaceSource(http, stats, "k").fill(PLACE, frozenset()) == {}
    assert seen == []


def test_google_call_cap_stops_further_calls():
    http, stats, seen = make_http(json_response({"places": []}))
    g = GooglePlaceSource(http, stats, "k", max_calls=2)
    g.search_nearby(category="음식점", lat=1, lng=2, radius_m=10)
    g.search_nearby(category="음식점", lat=1, lng=2, radius_m=10)
    with pytest.raises(SourceError, match="상한"):
        g.search_nearby(category="음식점", lat=1, lng=2, radius_m=10)
    assert len(seen) == 2


def test_google_never_retries_even_on_server_error():
    http, stats, seen = make_http(json_response({}, status=503), retries=3)
    with pytest.raises(SourceError):
        GooglePlaceSource(http, stats, "k").search_nearby(category="음식점", lat=1, lng=2, radius_m=10)
    assert len(seen) == 1 and stats.count("google") == 1

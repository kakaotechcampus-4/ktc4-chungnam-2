"""실제 외부 API 호출 — 기본 실행에서 제외된다. `python -m pytest -m live places -s`로만 돈다.

키는 backend/.env에서 읽는다. 키가 없는 소스는 skip. 구글은 과금이 있으니 호출을 한 번씩만 한다.
영구 저장은 하지 않는다 — 응답 필드 이름만 출력해 for_Root.md 관찰 기록에 옮긴다.
"""

import httpx
import pytest

from common.settings import settings
from places import api
from places.http import CallStats, SourceHttp

pytestmark = pytest.mark.live

SEONGSU = dict(lat=37.5445, lng=127.0561, radius_m=500)   # 성수동


@pytest.fixture(scope="module")
def sources():
    stats = CallStats()
    http = SourceHttp(httpx.Client(timeout=settings.places_http_timeout_s), stats, retries=1)
    return api.build_sources(http, stats), stats


def _need(src):
    if not src.is_configured():
        pytest.skip(f"{src.name} 키가 .env에 없다")


def test_kakao_nearby(sources):
    srcs, _ = sources
    _need(srcs["kakao"])
    found = srcs["kakao"].search_nearby(category="카페", **SEONGSU)
    assert found and all(p.place_id.startswith("kakao:") for p in found)
    print("kakao:", len(found), found[0])


def test_naver_nearby(sources):
    srcs, _ = sources
    _need(srcs["naver"])
    found = srcs["naver"].search_nearby(category="카페", lat=SEONGSU["lat"], lng=SEONGSU["lng"], radius_m=20000)
    print("naver:", len(found), found[:1])
    assert isinstance(found, list)


def test_google_fill_one_place(sources):
    srcs, stats = sources
    _need(srcs["google"])
    base = srcs["kakao"].search_nearby(category="음식점", **SEONGSU) if srcs["kakao"].is_configured() else []
    if not base:
        pytest.skip("카카오로 기준 장소를 못 얻었다")
    got = srcs["google"].fill(base[0], frozenset({"rating", "price_level", "opening_hours"}))
    print("google fill:", base[0].name, got, "calls:", stats.snapshot())
    assert stats.count("google") == 1

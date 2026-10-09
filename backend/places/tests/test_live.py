"""실제 외부 API 호출 — 기본 실행에서 제외된다. `python -m pytest -m live places -s`로만 돈다.

키는 backend/.env에서 읽는다. 키가 없는 소스는 skip.
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
    return api.build_sources(http), stats


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


def test_kakao_keyword_search_by_name(sources):
    srcs, _ = sources
    _need(srcs["kakao"])
    found = srcs["kakao"].search_by_name(query="성수 칼국수", lat=SEONGSU["lat"], lng=SEONGSU["lng"], limit=5)
    print("kakao name search:", [(p.name, p.lat, p.lng) for p in found])
    assert found and all(p.name and p.lat and p.lng for p in found)
    assert all(p.place_id.startswith("kakao:") for p in found)

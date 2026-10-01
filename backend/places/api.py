"""places 공개 접점 — 다른 모듈은 이 함수들만 부른다(backend/CLAUDE.md). 서비스는 프로세스당 하나."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Sequence

import httpx

from common.settings import settings
from places.http import CallStats, SourceHttp
from common.errors import AppError
from places.ratelimit import SlidingWindowLimiter
from places.samples import search_samples
from places.schemas import (
    Area, FactLabel, PlaceHint, PlaceInfo, PlaceMatch, PlaceRef, PlaceSearchResult, ResolvedCoords,
)
from places.service import PlaceService, to_result
from places.sources.base import PlaceSource
from places.sources.google import GooglePlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource

log = logging.getLogger("pingo.places")
_STATS = CallStats()
search_limiter = SlidingWindowLimiter(settings.places_search_per_min)   # 사용자당 분당 상한, 인메모리


def call_counts() -> dict[str, int]:
    """소스별 실제 HTTP 호출 횟수(프로세스 누적)."""
    return _STATS.snapshot()


def build_sources(http: SourceHttp, stats: CallStats = _STATS) -> dict[str, PlaceSource]:
    return {
        "kakao": KakaoPlaceSource(http, settings.kakao_rest_api_key),
        "naver": NaverPlaceSource(http, settings.naver_search_client_id, settings.naver_search_client_secret),
        "google": GooglePlaceSource(http, stats, settings.google_places_api_key,
                                    max_calls=settings.places_google_max_calls),
    }


@lru_cache(maxsize=1)
def _service() -> PlaceService:
    client = httpx.Client(timeout=settings.places_http_timeout_s)
    http = SourceHttp(client, _STATS, retries=settings.places_http_retries)
    available = build_sources(http)
    ordered = [available[n] for n in settings.places_sources]
    log.info("places.sources order=%s", ", ".join(
        f"{s.name}({'key' if s.is_configured() else 'NO KEY'})" for s in ordered))
    return PlaceService(ordered)


def search_nearby(category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    return _service().search_nearby(category, areas)


def get_raw_facts(place_id: str) -> dict[str, Any]:
    return _service().get_raw_facts(place_id)


def resolve_place(source: str, place_id: str | None, lat: float | None, lng: float | None) -> ResolvedCoords:
    return _service().resolve(source, place_id, lat, lng)


def _is_dev() -> bool:
    return settings.places_mode == "dev"


def check_search_rate(user_id: str) -> None:
    """GET /places/search 사용자당 호출 상한. 카카오 응답 헤더에 쿼터가 없어 서버에서 직접 센다."""
    if not search_limiter.allow(user_id):
        raise AppError("RATE_LIMITED")


def search_by_name(query: str, near: tuple[float, float] | None, limit: int) -> list[PlaceSearchResult]:
    """이름 검색. dev 모드는 카카오를 부르지 않고 고정 샘플 5곳(이름 부분 일치)을 돌려준다."""
    if _is_dev():
        lat, lng = near if near else (None, None)
        return [to_result(p) for p in search_samples(query, lat, lng, limit)]
    return _service().search_by_name(query, near, limit)


# ---- 자체 장소 DB 공개 함수 (docs/architecture.md "places 공개 함수 계약", #189·#190·#195) ----
# PR 1: 시그니처만 고정한다. 실제 구현은 PR 2(#189). pins·recommend는 places.testing.FakePlaces로 개발한다.
# 카카오 원자료는 이 함수들의 입출력 어디에도 없다 — kakao_place_id·kakao_place_url만 예외.

def match_place(hint: PlaceHint) -> PlaceMatch | None:
    """힌트에 맞는 자체 DB 장소 한 건. 읽기 전용. 반경 300m·후보 수 상한·분류 일치·이름 일치를 모두 만족할 때만,
    확신이 낮으면 None."""
    raise NotImplementedError("places.api.match_place — #189 PR 2")


def record_kakao_match(place_id: str, kakao_place_id: str, kakao_place_url: str) -> None:
    """매칭된 장소에 카카오 장소 ID·URL·확인 일자만 기록한다(핀 생성과 같은 트랜잭션). 이미 있으면 덮어쓴다."""
    raise NotImplementedError("places.api.record_kakao_match — #189 PR 2")


def pinnable_flags(hints: Sequence[PlaceHint]) -> list[bool]:
    """힌트마다 match_place가 성공할지 읽기만 해서 계산한다. 카카오 ID를 기록하지 않는다."""
    raise NotImplementedError("places.api.pinnable_flags — #189 PR 2")


def get_places(place_ids: Sequence[str]) -> dict[str, PlaceInfo]:
    """이름·좌표·분류·kakao_place_url을 배치로 조회한다. 없는 ID는 키에서 빠진다."""
    raise NotImplementedError("places.api.get_places — #189 PR 2")


def search_nearby_own(category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    """반경 안의 영업 중(status='open') 장소의 place_id·좌표. 분류는 음식점·카페·관광지."""
    raise NotImplementedError("places.api.search_nearby_own — #189 PR 2")


def get_facts(place_ids: Sequence[str]) -> dict[str, list[FactLabel]]:
    """place_facts의 fact_key·value·confidence를 그대로. 라벨이 없으면 빈 리스트. unknown_policy는 호출하는 쪽이 적용한다."""
    raise NotImplementedError("places.api.get_facts — #189 PR 2")

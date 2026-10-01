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
from places.schemas import Area, PlaceRef, PlaceSearchResult, ResolvedCoords
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

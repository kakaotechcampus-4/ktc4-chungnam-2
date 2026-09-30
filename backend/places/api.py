"""places 공개 접점 — 다른 모듈은 이 함수들만 부른다(backend/CLAUDE.md). 서비스는 프로세스당 하나."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Sequence

import httpx

from common.settings import settings
from places.cache import TTLCache
from places.http import CallStats, SourceHttp
from places.schemas import Area, PlaceRef, ResolvedCoords
from places.service import PlaceService
from places.sources.base import PlaceSource, RawPlace
from places.sources.google import GooglePlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource

log = logging.getLogger("pingo.places")
_STATS = CallStats()


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
    cache: TTLCache[RawPlace] = TTLCache(settings.places_cache_ttl_s)
    return PlaceService(ordered, cache)


def search_nearby(category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    return _service().search_nearby(category, areas)


def get_raw_facts(place_id: str) -> dict[str, Any]:
    return _service().get_raw_facts(place_id)


def resolve_place(source: str, place_id: str | None, lat: float | None, lng: float | None) -> ResolvedCoords:
    return _service().resolve(source, place_id, lat, lng)

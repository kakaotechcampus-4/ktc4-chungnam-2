"""places 실시간 게이트웨이의 본체(명령형 셸). 판단은 fallback.py, 캐시는 cache.py, 호출은 sources/.

DB에 아무것도 쓰지 않는다(#53 결정 전) — 검색 결과는 메모리 TTL 캐시에만 잠시 머문다.
"""

from __future__ import annotations

from typing import Any, Sequence

from common.errors import AppError
from places import fallback
from places.cache import TTLCache
from places.http import SourceError
from places.schemas import Area, PlaceRef, PlaceSearchResult, PlaceSourceInfo, ResolvedCoords
from places.sources.base import PlaceSource, RawPlace, distance_m

_ENRICHED = "enriched:"
_MAX_ECHO_DRIFT_M = 200.0   # search 경로에서 echo 좌표가 캐시 좌표와 이만큼 넘게 다르면 거절한다


class PlaceService:
    def __init__(self, sources: Sequence[PlaceSource], cache: TTLCache[RawPlace]) -> None:
        self._sources = list(sources)
        self._cache = cache

    def search_nearby(self, category: str, areas: Sequence[Area]) -> list[PlaceRef]:
        seen: dict[str, RawPlace] = {}
        for area in areas:
            found = fallback.search_with_fallback(
                self._sources, category=category, lat=area.lat, lng=area.lng, radius_m=area.radius_m
            )
            for place in found:
                seen.setdefault(place.place_id, place)
        for place in seen.values():
            self._cache.put(place.place_id, place)
        return [PlaceRef(p.place_id, p.lat, p.lng) for p in seen.values()]

    def search_by_name(self, query: str, near: tuple[float, float] | None, limit: int) -> list[PlaceSearchResult]:
        """이름 검색(#180). 결과는 메모리 캐시에만 둔다 — resolve가 나중에 echo 좌표를 대조한다.
        0건이면 []. 소스가 전부 실패하면 503 PLACES_UNAVAILABLE."""
        lat, lng = near if near else (None, None)
        try:
            found = fallback.search_by_name_with_fallback(self._sources, query=query, lat=lat, lng=lng, limit=limit)
        except SourceError as exc:
            raise AppError("PLACES_UNAVAILABLE") from exc
        return self.remember_and_convert(found)

    def remember_and_convert(self, found: list[RawPlace]) -> list[PlaceSearchResult]:
        for place in found:
            self._cache.put(place.place_id, place)
        return [_to_result(p) for p in found]

    def get_raw_facts(self, place_id: str) -> dict[str, Any]:
        """캐시에 있는 장소의 원자료(층1·2). 없으면 {} — 못 찾은 것이지 "정보 없음"이 아니다."""
        place = self._cache.get(place_id)
        if place is None:
            return {}
        if self._cache.get(_ENRICHED + place_id) is None:
            place = fallback.enrich(place, self._sources)
            self._cache.put(place_id, place)
            self._cache.put(_ENRICHED + place_id, place)   # 시도 표시 — 못 채운 필드로 과금 호출을 반복하지 않는다
        return _facts(place)

    def resolve(self, source: str, place_id: str | None, lat: float | None, lng: float | None) -> ResolvedCoords:
        if source == "coordinate":
            if lat is None or lng is None:
                raise AppError("VALIDATION_ERROR", "lat/lng가 필요합니다")
            return ResolvedCoords(place_id or f"coord:{lat:.6f},{lng:.6f}", lat, lng)
        if not place_id:
            raise AppError("VALIDATION_ERROR", "place_id가 필요합니다")
        if lat is None or lng is None:
            cached = self._cache.get(place_id)
            if cached is None:
                raise AppError("VALIDATION_ERROR", "장소를 찾지 못했습니다 — lat/lng를 함께 보내야 합니다")
            lat, lng = cached.lat, cached.lng
        else:
            cached = self._cache.get(place_id)
            # 캐시에 없으면(만료) echo 좌표를 그대로 쓴다 — coordinate 경로가 이미 임의 좌표를 받으니 위험이 늘지 않는다
            if cached is not None and distance_m(lat, lng, cached.lat, cached.lng) > _MAX_ECHO_DRIFT_M:
                raise AppError("VALIDATION_ERROR", "검색 결과의 좌표와 다릅니다 — 검색 결과의 lat/lng를 그대로 보내야 합니다")
        return ResolvedCoords(place_id, lat, lng)


def _facts(place: RawPlace) -> dict[str, Any]:
    raw = {
        "name": place.name, "category": place.category, "address": place.address, "place_url": place.place_url,
        "phone": place.phone, "rating": place.rating, "rating_count": place.rating_count,
        "price_level": place.price_level,
        "opening_hours": list(place.opening_hours) if place.opening_hours else None,
    }
    return {k: v for k, v in raw.items() if v is not None}


def _to_result(place: RawPlace) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=place.place_id,
        place_name=place.name[:100],   # 핀 생성 요청의 place_name 상한(100)과 같다
        lat=place.lat,
        lng=place.lng,
        category=place.category,       # 소스가 추정한 제안값 — 핀의 category는 사용자가 정한다
        address=place.address[:200] if place.address else None,
        place_source=PlaceSourceInfo(provider=place.source, url=place.place_url),
    )

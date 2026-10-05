"""소스 폴백·보완 로직. 어느 소스를 부를지 정하는 판단만 있고 설정·캐시는 모른다.

- 검색: 우선순위 순으로 시도해 결과가 있는 첫 소스가 이긴다(실패·키 없음·0건이면 다음 소스).
- 보완: 원 소스가 못 준 층2 필드만 다음 소스에 묻는다. 이미 채워진 필드는 다시 조회하지 않는다.
"""

from __future__ import annotations

import logging
from typing import Sequence

from places.http import SourceError
from places.sources.base import ENRICHABLE_FIELDS, NameSearchable, PlaceSource, RawPlace

log = logging.getLogger("pingo.places")


def search_with_fallback(
    sources: Sequence[PlaceSource], *, category: str, lat: float, lng: float, radius_m: int
) -> list[RawPlace]:
    for src in sources:
        if not src.is_configured():
            log.info("places.skip source=%s reason=no_key", src.name)
            continue
        try:
            found = src.search_nearby(category=category, lat=lat, lng=lng, radius_m=radius_m)
        except SourceError as exc:
            log.warning("places.fallback source=%s reason=%s", src.name, exc)
            continue
        if found:
            return found
        log.info("places.fallback source=%s reason=empty", src.name)
    return []


def enrich(place: RawPlace, sources: Sequence[PlaceSource], wanted: frozenset[str] = ENRICHABLE_FIELDS) -> RawPlace:
    """비어 있는 wanted 필드를 우선순위 순으로 채운다. 다 채워지면 멈춘다."""
    for src in sources:
        todo = place.missing() & wanted
        if not todo:
            break
        if src.name in place.contributed_by or not src.is_configured():
            continue
        ask = todo & src.provides
        if not ask:
            continue   # 이 소스는 남은 필드를 못 준다 — 호출하지 않는다
        try:
            fields = src.fill(place, ask)
        except SourceError as exc:
            log.warning("places.enrich source=%s reason=%s", src.name, exc)
            continue
        place = place.merged(fields, src.name, ask)
    return place


def search_by_name_with_fallback(
    sources: Sequence[PlaceSource], *, query: str, lat: float | None, lng: float | None, limit: int
) -> list[RawPlace]:
    """이름 검색. 결과가 있는 첫 소스가 이긴다. 성공했지만 0건이면 [] — 지어내지 않는다.
    이름 검색이 가능한 소스가 하나도 성공하지 못하면(키 없음·장애·상한·소스 없음) SourceError."""
    succeeded = False
    for src in sources:
        if not isinstance(src, NameSearchable):
            continue
        if not src.is_configured():
            log.info("places.skip source=%s reason=no_key", src.name)
            continue
        try:
            found = src.search_by_name(query=query, lat=lat, lng=lng, limit=limit)
        except SourceError as exc:
            log.warning("places.fallback source=%s reason=%s", src.name, exc)
            continue
        succeeded = True
        if found:
            return found
    if succeeded:
        return []
    raise SourceError("이름 검색을 할 수 있는 소스가 없다(키 없음·장애·호출 상한)")

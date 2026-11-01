"""places 실시간 게이트웨이의 본체(명령형 셸). 판단은 fallback.py, 호출은 sources/.

지도 API 응답은 어디에도 남기지 않는다(#188, #53 결정): DB 저장 없음, 메모리 캐시 없음, LLM 전달 없음.
카카오 실시간 검색 결과는 그 요청의 응답(화면 표시)으로만 쓰이고 바로 버려진다.
"""

from __future__ import annotations

from typing import Sequence

from common.errors import AppError
from places import fallback
from places.http import SourceError
from places.schemas import PlaceSearchResult, PlaceSourceInfo
from places.sources.base import PlaceSource, RawPlace


class PlaceService:
    def __init__(self, sources: Sequence[PlaceSource]) -> None:
        self._sources = list(sources)

    def search_by_name(self, query: str, near: tuple[float, float] | None, limit: int) -> list[PlaceSearchResult]:
        """이름 검색(#180) — 화면 표시용. 0건이면 []. 소스가 전부 실패하면 503 PLACES_UNAVAILABLE."""
        lat, lng = near if near else (None, None)
        try:
            found = fallback.search_by_name_with_fallback(self._sources, query=query, lat=lat, lng=lng, limit=limit)
        except SourceError as exc:
            raise AppError("PLACES_UNAVAILABLE") from exc
        return [to_result(p) for p in found]


def to_result(place: RawPlace) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=place.place_id,
        place_name=place.name[:100],   # 핀 생성 요청의 place_name 상한(100)과 같다
        lat=place.lat,
        lng=place.lng,
        category=place.category,       # 소스가 추정한 제안값 — 핀의 category는 사용자가 정한다
        address=place.address[:200] if place.address else None,
        place_source=PlaceSourceInfo(provider=place.source, url=place.place_url),
    )

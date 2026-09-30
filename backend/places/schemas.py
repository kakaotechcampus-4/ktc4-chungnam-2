"""places가 다른 모듈에 내보내는 값 타입. 다른 모듈은 이 파일과 api.py만 쓴다(backend/CLAUDE.md).

RawPlace(소스 응답 원형)는 places 내부 타입이라 여기 없다 — 밖으로는 좌표·식별자만 나간다.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Area:
    """검색 원 하나. 중심 좌표 + 반경(m)."""

    lat: float
    lng: float
    radius_m: int


@dataclass(frozen=True)
class PlaceRef:
    """검색 결과 한 곳 — 식별자와 좌표뿐이다. place_id는 "<소스>:<소스 내 id>" 형태."""

    place_id: str
    lat: float
    lng: float


@dataclass(frozen=True)
class ResolvedCoords:
    place_id: str
    lat: float
    lng: float


# ---- GET /places/search 응답 (docs/api-spec.yaml PlaceSearchResult, #180) ----

class PlaceSourceInfo(BaseModel):
    provider: Literal["kakao", "naver", "google"]
    url: str | None = None


class PlaceSearchResult(BaseModel):
    place_id: str
    place_name: str
    lat: float
    lng: float
    category: Literal["음식점", "카페", "숙소", "관광지", "기타"] | None = None   # 소스가 추정한 제안값
    address: str | None = None
    place_source: PlaceSourceInfo | None = None

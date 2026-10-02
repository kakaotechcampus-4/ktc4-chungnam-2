"""places가 다른 모듈에 내보내는 값 타입. 다른 모듈은 이 파일과 api.py만 쓴다(backend/CLAUDE.md).

RawPlace(소스 응답 원형)는 places 내부 타입이라 여기 없다 — 밖으로는 좌표·식별자만 나간다.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Area:
    """검색 원 하나. 중심 좌표 + 반경(m)."""

    lat: float
    lng: float
    radius_m: int


@dataclass(frozen=True)
class PlaceRef:
    """검색 결과 한 곳 — 식별자와 좌표뿐이다. 자체 DB 함수(search_nearby_own)에서는 place_id가 places.id(UUID 문자열)다.
    (기존 카카오 실시간 search_nearby는 "kakao:<id>" — #190에서 recommend가 옮겨 가면 지운다.)"""

    place_id: str
    lat: float
    lng: float


# ---- 자체 장소 DB 공개 함수의 입출력 (docs/architecture.md "places 공개 함수 계약", #189·#190·#195) ----
# 카카오 원자료는 여기 어디에도 없다. kakao_place_id·kakao_place_url만 예외(저장 허용 범위, #53).

@dataclass(frozen=True)
class PlaceHint:
    """match_place의 입력 — 사용자가 고른 카카오 검색 결과에서 온 힌트. 저장하지 않는다."""

    kakao_place_id: str | None
    name: str
    lat: float
    lng: float
    category: str


@dataclass(frozen=True)
class PlaceMatch:
    """match_place의 결과 — 짝이 된 자체 DB 장소. 이름·좌표는 자체 데이터(places)에서 온 값이다."""

    place_id: str
    name: str
    lat: float
    lng: float
    category: str


@dataclass(frozen=True)
class PlaceInfo:
    """get_places의 결과 — 핀·후보 응답을 채우는 값."""

    place_id: str
    name: str
    lat: float
    lng: float
    category: str
    kakao_place_url: str | None = None


@dataclass(frozen=True)
class FactLabel:
    """get_facts의 결과 한 줄 — place_facts 그대로. unknown_policy는 호출하는 쪽이 적용한다."""

    fact_key: str
    value: Any
    confidence: Literal["known", "unknown"]


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
    pinnable: bool | None = None   # 자체 DB에 짝이 있어 핀으로 만들 수 있는가(#238). 계산 못 했으면 생략

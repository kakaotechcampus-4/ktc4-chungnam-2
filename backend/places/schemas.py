"""places가 다른 모듈에 내보내는 값 타입. 다른 모듈은 이 파일과 api.py만 쓴다(backend/CLAUDE.md).

RawPlace(소스 응답 원형)는 places 내부 타입이라 여기 없다 — 밖으로는 좌표·식별자만 나간다.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from common import categories


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
    can_recommend: bool = True   # 추천 후보 풀에 넣어도 되는가(places.curated 그대로, #743). search_nearby_own만 실제 값을 채운다 — 기본 True라 다른 호출자는 그대로다


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
    address: str | None = None   # 선택 — 이름 유사도를 보완하는 비교용(#500). 비교에만 쓰고 저장·로깅하지 않는다(#53)


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
    source: str | None = None   # 데이터 출처 — "permit"(인허가 공공데이터) | "tourapi"(한국관광공사). 가드레일 5 출처 표시용(#242)
    curated: bool = False       # 정예(사람이 직접 조사·납품, places.curated) — 출처를 "정예 조사"로 표시할 때 쓴다(#681). 기본 False라 기존 호출자는 그대로다
    address: str | None = None  # 자체 DB 주소 — 장소 링크의 동네를 자를 때 쓴다(places.api.place_link, #799). 응답에 그대로 싣지 않는다


@dataclass(frozen=True)
class FactLabel:
    """get_facts의 결과 한 줄 — place_facts 그대로. unknown_policy는 호출하는 쪽이 적용한다."""

    fact_key: str
    value: Any
    confidence: Literal["known", "unknown"]


@dataclass(frozen=True)
class PlaceHours:
    """get_hours의 결과 — place_hours 그대로(#690). None인 칸은 모름. 요일 단위 판정은 core.day_open_status."""

    hours: dict[str, list[list[str]]] | None = None   # {"월": [["11:00","21:00"]], …}, 빈 목록 = 휴무, "26:00" = 다음 날 02:00
    closed_days: list[str] | None = None               # 매주 쉬는 요일, [] = 연중무휴
    closed_note: str | None = None                     # 표시용 — 판단에 쓰지 않는다
    hours_note: str | None = None


# ---- GET /places/search 응답 (docs/api-spec.yaml PlaceSearchResult, #180) ----

class PlaceSourceInfo(BaseModel):
    provider: Literal["kakao", "naver", "google", "permit", "tourapi"]
    url: str | None = None


class PlaceSearchResult(BaseModel):
    place_id: str
    place_name: str
    lat: float
    lng: float
    category: Literal[categories.all_categories()] | None = None   # 소스가 추정한 제안값
    address: str | None = None
    place_source: PlaceSourceInfo | None = None
    pinnable: bool | None = None   # 자체 DB에 짝이 있어 핀으로 만들 수 있는가(#238). 계산 못 했으면 생략


# ---- POST /places/from-link 응답 (docs/api-spec.yaml LinkParseResult, #474) ----

class LinkParseResult(BaseModel):
    provider: Literal["google", "kakao"]
    name_hint: str | None = None          # 구글 링크에 든 이름(사용자가 붙인 값). 카카오 링크에는 없다
    kakao_place_id: str | None = None     # 카카오 링크의 장소 ID — 저장이 허용된 유일한 카카오 값
    matches: list[PlaceSearchResult]      # 자체 DB 장소만(pinnable=true). 없으면 빈 배열
    needs_search_query: bool

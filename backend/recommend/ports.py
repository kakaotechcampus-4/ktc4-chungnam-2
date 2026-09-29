"""
recommend가 다른 모듈에 대해 갖는 의존을 프로토콜로 좁혀둔다(pins/ports.py·authz/ports.py와
같은 패턴). places(#14)·seeding(#13)이 아직 없어 이 파일의 두 게이트웨이는 지금 dev 스텁으로만
채워진다(recommend/deps.py) — 실구현이 올 때 이 Protocol만 만족하면 교체된다.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Circle:
    """반경 사유 하나(또는 병합된 지역)를 나타내는 원. 앵커 좌표 + 반경(m)."""

    anchor_lat: float
    anchor_lng: float
    radius_m: int


@dataclass(frozen=True)
class PlaceStub:
    """PlaceSearchGateway가 돌려주는 최소 정보 — places(#14) 전까지는 place_id/좌표뿐이다."""

    place_id: str
    lat: float
    lng: float


class PlaceSearchGateway(Protocol):
    """반경 안 장소 검색(5-6 1단계 이전, 후보 풀 확보). places(#14) 실구현 전까지는
    recommend/deps.py의 dev 스텁이 이 자리를 채운다."""

    def search_nearby(self, *, category: str, circles: Sequence[Circle]) -> list[PlaceStub]: ...


class PlaceFactsGateway(Protocol):
    """장소 하나의 원자료(층1·2)를 조회한다(architecture.md 3층 모델) — recommend는 이 값을
    llm.label_place에 그대로 넘겨 층3(라벨) 판정을 받는다. place_facts(#14)가 없으면 항상
    빈 dict를 반환해도 안전하다 — llm.label_place가 빈 값을 전부 unknown으로 응답하고,
    이 모듈이 docs/constraints.md의 unknown_policy로 마저 처리한다."""

    def get_raw_facts(self, place_id: str) -> Mapping[str, Any]: ...

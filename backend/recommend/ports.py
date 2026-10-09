"""
recommend가 다른 모듈에 대해 갖는 의존을 프로토콜로 좁혀둔다(pins/ports.py·authz/ports.py와
같은 패턴). places(#14)·seeding(#13)이 아직 없어 이 파일의 두 게이트웨이는 지금 dev 스텁으로만
채워진다(recommend/deps.py) — 실구현이 올 때 이 Protocol만 만족하면 교체된다.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from llm.schemas import EvidenceLine
from places.schemas import FactLabel


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
    # 가드레일5 출처 — {"provider": "kakao"|"naver"|"google"|"permit"|"tourapi", "url"?: str}. places(#14)가 실구현되면
    # 채운다. dev 스텁은 출처가 없으므로 None(없는 출처를 지어내지 않는다).
    source: Mapping[str, Any] | None = None


class PlaceSearchGateway(Protocol):
    """반경 안 장소 검색(5-6 1단계 이전, 후보 풀 확보). 실제 모드는 places.api.search_nearby_own(자체 DB)
    에 위임한다 — 후보의 place_id·좌표·이름은 전부 places에서 온다(#190). dev 모드는 recommend/deps.py의
    스텁이 채운다."""

    def search_nearby(self, *, category: str, circles: Sequence[Circle]) -> list[PlaceStub]: ...

    def get_names(self, place_ids: Sequence[str]) -> Mapping[str, str]:
        """후보 응답의 place_name용 — 없는 ID는 키에서 빠진다."""
        ...


class PlaceFactsGateway(Protocol):
    """장소 라벨 조회(층3). 실제 모드는 places.api.get_facts(자체 DB의 place_facts)를 그대로 돌려준다.
    **요청 중에 모델로 라벨을 만들지 않는다**(#190, v1) — 라벨이 없는 장소는 빈 리스트이고, recommend가
    confidence=unknown으로 보고 docs/constraints.md의 unknown_policy를 적용한다. 카카오 원자료는 이
    인터페이스 어디에도 없다."""

    def get_facts(self, place_ids: Sequence[str]) -> Mapping[str, Sequence[FactLabel]]: ...


class EvidencePlanGateway(Protocol):
    """② 사유 구조화(요청 중 유일한 모델 호출). 실제 모드는 llm.api.plan_evidence에 Luna 플래너를 물려 위임하고,
    dev 모드는 입력을 검증만 하고 통과시키는 스텁이다(#219). 입력 글마다 근거 줄 묶음 하나를 같은 순서로 돌려주고,
    실패하면 PlanEvidenceFailed를 올린다 — 빈 결과로 삼키지 않는다."""

    def plan_evidence(self, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]: ...

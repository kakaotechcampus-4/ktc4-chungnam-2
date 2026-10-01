"""
FastAPI 의존성 배선. places(#14)/seeding(#13)이 아직 없어, pins/deps.py와 같은 패턴으로 그
자리를 채우는 개발용 어댑터를 여기 둔다 — settings.places_mode를 그대로 재사용한다(recommend
전용 설정 키를 새로 만들지 않는다: "places가 실구현인지"라는 같은 질문이기 때문).

**dev 스텁의 한계(recommend/for_Root.md에 자세히)**: `DevPlaceSearchGateway`는 실제 장소
검색이 아니라 원 중심에서 고정 오프셋만큼 떨어진 좌표에 합성 place_id를 만드는 자리채움이다 —
"AI 없이도 FE+BE 코어 루프가 도는 데모가 우선"(CLAUDE.md 이슈 운영 원칙)을 만족시키기 위한
결정이고, 실제 장소 데이터가 아니다. `DevPlaceFactsGateway`는 항상 빈 라벨을 돌려줘 모든
fact_key가 unknown이 된다(architecture.md 3절 — 라벨 없이도 unknown_policy 분기로 정상 처리된다는
전제 그대로).

**실제 모드(#190)**: `Real*` 게이트웨이는 places.api의 자체 DB 함수(search_nearby_own·get_places·
get_facts)에만 위임한다. 요청 중 모델 호출도 카카오 원자료도 이 경로에 없다.
"""

from typing import Mapping, Sequence

from fastapi import Depends
from sqlalchemy.orm import Session

from common.adapters import select
from common.database import get_db_session
from common.settings import settings
from places import api as places_api
from places.schemas import Area, FactLabel
from recommend.ports import Circle, PlaceFactsGateway, PlaceSearchGateway, PlaceStub


class DevPlaceSearchGateway:
    # 앵커에서 대략 100~150m 떨어진 6개 자리 — 좌표 소수 4자리(약 11m 단위) 오프셋. 튜플(불변) —
    # 클래스 속성으로 가변 리스트를 두면 인스턴스끼리 공유 상태가 될 위험이 있다(ruff RUF012).
    _OFFSETS = ((0.001, 0.001), (-0.001, 0.001), (0.001, -0.001), (-0.001, -0.001), (0.0015, 0.0), (0.0, 0.0015))

    def search_nearby(self, *, category: str, circles: list[Circle]) -> list[PlaceStub]:
        if not circles:
            return []
        anchor = circles[0]  # v1 — 첫 원(가장 먼저 확정된 지역) 기준으로만 채운다
        return [
            PlaceStub(
                place_id=f"dev-seed:{category}:{anchor.anchor_lat:.4f}:{anchor.anchor_lng:.4f}:{i}",
                lat=anchor.anchor_lat + dlat,
                lng=anchor.anchor_lng + dlng,
            )
            for i, (dlat, dlng) in enumerate(self._OFFSETS)
        ]


    def get_names(self, place_ids: Sequence[str]) -> Mapping[str, str]:
        return {}  # 합성 place_id라 이름이 없다


class DevPlaceFactsGateway:
    def get_facts(self, place_ids: Sequence[str]) -> Mapping[str, Sequence[FactLabel]]:
        return {place_id: [] for place_id in place_ids}  # 라벨 없음 = 전부 unknown(unknown_policy 그대로 적용)


class RealPlaceSearchGateway:
    """자체 장소 DB(places.api.search_nearby_own) 반경 검색 — 후보의 place_id·좌표는 places에서 온다(#190).
    db를 넘기면 그 세션으로(테스트), 안 넘기면 places가 짧은 세션을 직접 연다."""

    def __init__(self, db: Session | None = None):
        self._db = db

    def search_nearby(self, *, category: str, circles: Sequence[Circle]) -> list[PlaceStub]:
        areas = [Area(lat=c.anchor_lat, lng=c.anchor_lng, radius_m=c.radius_m) for c in circles]
        return [PlaceStub(place_id=r.place_id, lat=r.lat, lng=r.lng) for r in places_api.search_nearby_own(category, areas, db=self._db)]

    def get_names(self, place_ids: Sequence[str]) -> Mapping[str, str]:
        return {pid: info.name for pid, info in places_api.get_places(list(place_ids), db=self._db).items()}


class RealPlaceFactsGateway:
    """자체 DB place_facts의 라벨을 그대로 돌려준다 — 모델 호출도 카카오 원자료도 없다(#190)."""

    def __init__(self, db: Session | None = None):
        self._db = db

    def get_facts(self, place_ids: Sequence[str]) -> Mapping[str, Sequence[FactLabel]]:
        return places_api.get_facts(list(place_ids), db=self._db)


def _real_place_search_gateway() -> PlaceSearchGateway:
    return RealPlaceSearchGateway()


def _real_place_facts_gateway() -> PlaceFactsGateway:
    return RealPlaceFactsGateway()


def _dev_place_search_gateway() -> PlaceSearchGateway:
    return DevPlaceSearchGateway()


def _dev_place_facts_gateway() -> PlaceFactsGateway:
    return DevPlaceFactsGateway()


get_place_search_gateway = select(
    "recommend.PlaceSearchGateway", settings.places_mode,
    {"dev": _dev_place_search_gateway, "real": _real_place_search_gateway}, "places #189",
)

get_place_facts_gateway = select(
    "recommend.PlaceFactsGateway", settings.places_mode,
    {"dev": _dev_place_facts_gateway, "real": _real_place_facts_gateway}, "places #189",
)


DbSession = Depends(get_db_session)
PlaceSearchGatewayDep = Depends(get_place_search_gateway)
PlaceFactsGatewayDep = Depends(get_place_facts_gateway)

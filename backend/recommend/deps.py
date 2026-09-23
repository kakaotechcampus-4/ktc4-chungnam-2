"""
FastAPI 의존성 배선. places(#14)/seeding(#13)이 아직 없어, pins/deps.py와 같은 패턴으로 그
자리를 채우는 개발용 어댑터를 여기 둔다 — settings.places_mode를 그대로 재사용한다(recommend
전용 설정 키를 새로 만들지 않는다: "places가 실구현인지"라는 같은 질문이기 때문).

**dev 스텁의 한계(recommend/for_Root.md에 자세히)**: `DevPlaceSearchGateway`는 실제 장소
검색이 아니라 원 중심에서 고정 오프셋만큼 떨어진 좌표에 합성 place_id를 만드는 자리채움이다 —
"AI 없이도 FE+BE 코어 루프가 도는 데모가 우선"(CLAUDE.md 이슈 운영 원칙)을 만족시키기 위한
결정이고, 실제 장소 데이터가 아니다. `DevPlaceFactsGateway`는 항상 빈 dict를 반환해
llm.label_place가 모든 fact_key를 unknown으로 응답하게 만든다(architecture.md 3절 — place_facts
없이도 unknown_policy 분기로 정상 처리된다는 전제 그대로).
"""

from fastapi import Depends

from common.adapters import select
from common.database import get_db_session
from common.settings import settings
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


class DevPlaceFactsGateway:
    def get_raw_facts(self, place_id: str) -> dict:
        return {}


def _dev_place_search_gateway() -> PlaceSearchGateway:
    return DevPlaceSearchGateway()


def _dev_place_facts_gateway() -> PlaceFactsGateway:
    return DevPlaceFactsGateway()


get_place_search_gateway = select(
    "recommend.PlaceSearchGateway", settings.places_mode,
    {"dev": _dev_place_search_gateway, "real": None}, "places #14",
)

get_place_facts_gateway = select(
    "recommend.PlaceFactsGateway", settings.places_mode,
    {"dev": _dev_place_facts_gateway, "real": None}, "places #14",
)


DbSession = Depends(get_db_session)
PlaceSearchGatewayDep = Depends(get_place_search_gateway)
PlaceFactsGatewayDep = Depends(get_place_facts_gateway)

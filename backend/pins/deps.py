"""
FastAPI 의존성 배선. places(#34)가 아직 없어, 그 자리를 채우는 개발용 어댑터를 여기 둔다.

membership·이벤트 발행·인증은 각각 authz.guard(+authz.deps)·common.events.record_event·
auth.deps로 이관됐다(mentor-review-plan.md #56 재정의) — 여기 남는 건 place gateway와
DB 세션 배선뿐이다.
"""

from fastapi import Depends

from common.adapters import select
from common.database import get_db
from common.errors import AppError
from common.settings import settings
from pins.ports import PinDraft, ResolvedPlace


class RequestEchoPlaceGateway:
    """places(#34) 전까지 쓰는 개발용 어댑터 — 요청에 온 lat/lng/place_id를 그대로 통과시킨다.
    link·search 경로는 실제 장소 조회가 없으니 좌표가 함께 오지 않으면 422로 막는다.
    coordinate 경로는 애초에 조회할 장소가 없다 — 좌표 자체를 장소 식별자로 합성한다
    (#33 중복 판정 기준이 확정되면 이 합성 규칙도 함께 바뀔 수 있다)."""

    def resolve(self, draft: PinDraft) -> ResolvedPlace:
        if draft.lat is None or draft.lng is None:
            raise AppError("VALIDATION_ERROR", "장소 조회(places)가 아직 없어 lat/lng를 함께 보내야 합니다")
        place_id = draft.place_id or draft.link_url
        if place_id is None:
            if draft.source != "coordinate":
                raise AppError("VALIDATION_ERROR", "place_id 또는 link_url이 필요합니다")
            place_id = f"coord:{draft.lat:.6f},{draft.lng:.6f}"
        return ResolvedPlace(place_id=place_id, lat=draft.lat, lng=draft.lng)


def _dev_place_gateway() -> RequestEchoPlaceGateway:
    return RequestEchoPlaceGateway()


get_place_gateway = select(
    "pins.PlaceGateway", settings.places_mode,
    {"dev": _dev_place_gateway, "real": None}, "places #34",
)


def get_db_session():
    yield from get_db()


DbSession = Depends(get_db_session)
PlaceGatewayDep = Depends(get_place_gateway)

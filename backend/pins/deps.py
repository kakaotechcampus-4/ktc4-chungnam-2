"""
FastAPI 의존성 배선. auth/maps/places/realtime이 아직 없어, 그 자리를 채우는 개발용 어댑터를
여기 둔다 — 이름에 "아직 진짜가 아니다"가 드러나게 해서 나중에 교체를 잊지 않게 한다.
각 모듈이 준비되면 이 파일의 Depends 대상만 바꾸면 되고, router.py는 건드리지 않는다.
"""

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from common.database import get_db
from pins.errors import PinError
from pins.ports import PinDraft, ResolvedPlace


def get_current_user_id(session: str | None = Cookie(default=None)) -> str | None:
    """auth(#4) 도착 시 이 함수 하나만 실제 세션 검증으로 교체한다.

    여기서 401을 직접 raise하지 않는다 — Depends 해석은 라우터 함수 진입보다 먼저 일어나서
    라우터의 try/except(PinError → 봉투 변환)를 비켜간다. common/errors.py(PR #49)가 들어와
    앱 레벨 예외 핸들러가 생기기 전까지는, None을 그대로 반환하고 각 라우터가
    require_user_id()로 검증한다.
    """
    return session


def require_user_id(viewer_id: str | None) -> str:
    if not viewer_id:
        raise PinError(401, "UNAUTHORIZED", "로그인이 필요합니다")
    return viewer_id


class RequestEchoPlaceGateway:
    """places(#34) 전까지 쓰는 개발용 어댑터 — 요청에 온 lat/lng/place_id를 그대로 통과시킨다.
    link·search 경로는 실제 장소 조회가 없으니 좌표가 함께 오지 않으면 422로 막는다.
    coordinate 경로는 애초에 조회할 장소가 없다 — 좌표 자체를 장소 식별자로 합성한다
    (#33 중복 판정 기준이 확정되면 이 합성 규칙도 함께 바뀔 수 있다)."""

    def resolve(self, draft: PinDraft) -> ResolvedPlace:
        if draft.lat is None or draft.lng is None:
            raise PinError(
                422,
                "VALIDATION_ERROR",
                "장소 조회(places)가 아직 없어 lat/lng를 함께 보내야 합니다",
            )
        place_id = draft.place_id or draft.link_url
        if place_id is None:
            if draft.source != "coordinate":
                raise PinError(422, "VALIDATION_ERROR", "place_id 또는 link_url이 필요합니다")
            place_id = f"coord:{draft.lat:.6f},{draft.lng:.6f}"
        return ResolvedPlace(place_id=place_id, lat=draft.lat, lng=draft.lng)


class AllowAllMembership:
    """maps(#19)/authz(#36) 전까지 쓰는 개발용 어댑터 — 항상 구성원으로 취급한다.
    이름 그대로 "아직 검증 안 함"이다. 실제 멤버십 확인이 들어오기 전엔 신뢰하지 않는다."""

    def is_member(self, map_id: str, user_id: str) -> bool:
        return True


class NullPublisher:
    """realtime(#13) 전까지 쓰는 개발용 어댑터 — 아무 것도 하지 않는다."""

    def publish(self, map_id: str, channel: str, type: str, payload: dict) -> None:
        return None


def get_db_session() -> Session:
    yield from get_db()


def get_place_gateway() -> RequestEchoPlaceGateway:
    return RequestEchoPlaceGateway()


def get_membership_gateway() -> AllowAllMembership:
    return AllowAllMembership()


def get_event_publisher() -> NullPublisher:
    return NullPublisher()


DbSession = Depends(get_db_session)
CurrentUserId = Depends(get_current_user_id)
PlaceGatewayDep = Depends(get_place_gateway)
MembershipGatewayDep = Depends(get_membership_gateway)
EventPublisherDep = Depends(get_event_publisher)

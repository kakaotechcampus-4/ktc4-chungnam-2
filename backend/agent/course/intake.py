"""확정 리스트의 핀을 동선 입력(Trip)으로 바꾼다. 순수 함수.

좌표를 알 수 없는 핀(실시간 핀 `pins.source='live'`, #382 — 서버는 카카오 장소 ID·검색어·메모만 저장한다)은 동선에서 빼고
"좌표를 알 수 없어 동선에서 빠졌어요"로 보여준다(기존 shortlist 동선 계산과 같은 처리). 카카오 좌표는 모델에 넣을 수 없다(#53).
빠진 핀은 코스에도, 모델 입력에도 들어가지 않는다 — 화면 문구용으로만 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from agent.course.constants import MIN_PLACES
from agent.course.core import MemberConstraint, Place, Trip

EXCLUDED_NO_COORDINATES = "NO_COORDINATES"
EXCLUDED_MESSAGE = "좌표를 알 수 없어 동선에서 빠졌어요"


@dataclass(frozen=True)
class PinInput:
    """확정 리스트의 핀 하나. 좌표가 없으면(실시간 핀) lat/lng가 None이다."""
    pin_id: str
    place_id: Optional[str]
    name: str
    category: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    labels: frozenset[str] = frozenset()

    @property
    def routable(self) -> bool:
        return self.place_id is not None and self.lat is not None and self.lng is not None


@dataclass(frozen=True)
class Excluded:
    pin_id: str
    name: str
    reason: str = EXCLUDED_NO_COORDINATES
    message: str = EXCLUDED_MESSAGE


@dataclass(frozen=True)
class TripBuild:
    trip: Optional[Trip]               # 코스를 짤 장소가 MIN_PLACES보다 적으면 None
    excluded: tuple[Excluded, ...]

    @property
    def too_few(self) -> bool:
        return self.trip is None


def build_trip(
    pins: Sequence[PinInput],
    days: Sequence[date],
    member_constraints: Sequence[MemberConstraint] = (),
    unknown_hours: str = "violation",
) -> TripBuild:
    """들어온 순서대로 p1, p2 … 별칭을 붙인다(빠진 핀은 번호를 쓰지 않는다)."""
    routable = [p for p in pins if p.routable]
    excluded = tuple(Excluded(p.pin_id, p.name) for p in pins if not p.routable)
    if len(routable) < MIN_PLACES:
        return TripBuild(None, excluded)
    places = tuple(
        Place(f"p{i + 1}", p.pin_id, p.place_id, p.name, p.category, p.lat, p.lng, p.labels)
        for i, p in enumerate(routable)
    )
    return TripBuild(Trip(places, tuple(days), tuple(member_constraints), unknown_hours), excluded)  # type: ignore[arg-type]

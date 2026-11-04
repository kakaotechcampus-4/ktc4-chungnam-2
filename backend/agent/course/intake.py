"""확정 리스트의 핀을 동선 입력(Trip)으로 바꾼다. 순수 함수.

좌표를 알 수 없는 핀(실시간 핀 `pins.source='live'`, #382 — 서버는 카카오 장소 ID·검색어·메모만 저장한다)은 동선에서 빼고
"좌표를 알 수 없어 동선에서 빠졌어요"로 보여준다(기존 shortlist 동선 계산과 같은 처리). 카카오 좌표는 모델에 넣을 수 없다(#53).
빠진 핀은 코스에도, 모델 입력에도 들어가지 않는다 — 화면 문구용으로만 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Optional, Sequence

from agent.course.constants import MIN_PLACES
from agent.course.core import Course, MemberConstraint, Place, Trip, day_alias

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
    scheduled_date: Optional[date] = None     # 사람이 확정 탭 일정에서 이 장소를 넣은 날(#1237). 없으면 미배정
    visit_order: Optional[int] = None         # 그날 안의 순서(일정의 visit_order). 점검이 사람이 정한 순서를 그대로 읽는다

    @property
    def routable(self) -> bool:
        return self.place_id is not None and self.lat is not None and self.lng is not None


@dataclass(frozen=True)
class Excluded:
    pin_id: str
    name: str
    reason: str = EXCLUDED_NO_COORDINATES
    message: str = EXCLUDED_MESSAGE


MODE_PLAN = "plan"        # 날짜에 넣은 장소 없음 — 처음부터 짠다
MODE_FILL = "fill"        # 일부만 넣음 — 넣은 곳은 고정하고 미배정만 나눈다
MODE_REVIEW = "review"    # 모두 넣음 — 고정뿐이라 나눌 것이 없다(점검은 다음 PR)


@dataclass(frozen=True)
class TripBuild:
    trip: Optional[Trip]               # 코스를 짤 장소가 MIN_PLACES보다 적으면 None
    excluded: tuple[Excluded, ...]
    locks: Mapping[str, str] = field(default_factory=dict)    # 사람이 날짜에 넣은 장소 별칭 → 날짜 별칭. AI는 옮기지 못한다
    schedule: Optional[Course] = None      # mode가 review일 때만: 사람이 정한 일정 그대로(날짜 위치별 장소 별칭, 그날 순서는 visit_order)

    @property
    def mode(self) -> Optional[str]:
        """코스를 시작할 때의 일정 상태(#1237). 좌표를 아는 확정 장소(= trip의 장소) 기준이다. trip이 없으면 None."""
        if self.trip is None:
            return None
        if not self.locks:
            return MODE_PLAN
        return MODE_REVIEW if len(self.locks) == len(self.trip.places) else MODE_FILL

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
    day_index = {d: i for i, d in enumerate(days)}      # 코스가 다루는 기간 밖 날짜(COURSE_DAYS_MAX 너머)에 넣은 장소는 고정하지 못한다
    locks = {
        f"p{i + 1}": day_alias(day_index[p.scheduled_date])
        for i, p in enumerate(routable) if p.scheduled_date in day_index
    }
    schedule = None
    if locks and len(locks) == len(routable):               # 모두 넣은 일정(review) — 점검이 그대로 읽는다. 순서 없는 장소는 확정 순서대로 뒤에
        order = {f"p{i + 1}": (p.visit_order is None, p.visit_order or 0, i) for i, p in enumerate(routable)}
        schedule = tuple(
            tuple(sorted((a for a, d in locks.items() if d == day_alias(k)), key=order.__getitem__)) for k in range(len(days))
        )
    return TripBuild(Trip(places, tuple(days), tuple(member_constraints), unknown_hours), excluded, locks, schedule)  # type: ignore[arg-type]

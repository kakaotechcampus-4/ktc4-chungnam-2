"""에이전트 루프의 상태(명세 4절 "상태"). 값 객체다 — 도구는 상태를 고치지 않고 새 상태를 돌려준다.

M1에서 이 상태를 agent_course_runs.state(jsonb)에 저장해 질문 뒤 재개에 쓴다. 그래서 상태에는 계산으로
다시 만들 수 있는 것(위반, 점수)과 다시 만들 수 없는 것(채택 이력, 영업시간 조회 결과, 고정)을 함께 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Optional

from agent.course import core
from agent.course.core import Course, Hours, Trip, Violation
from agent.course.schemas import Move


@dataclass(frozen=True)
class Trial:
    """try_move로 만든 가상 적용 결과. 채택하기 전에는 상태의 코스를 바꾸지 않는다."""
    trial_id: str
    move: Move
    course: Course
    violations: tuple[Violation, ...]


@dataclass(frozen=True)
class Commit:
    """채택 이력 한 칸. 0번은 초안이다. revert는 이 번호로 되돌린다."""
    step: int
    course: Course


@dataclass(frozen=True)
class State:
    trip: Trip
    hours: Hours
    course: Course
    violations: tuple[Violation, ...]
    history: tuple[Commit, ...]
    trials: tuple[Trial, ...] = ()
    trial_seq: int = 0
    locks: Mapping[str, str] = field(default_factory=dict)     # 장소 → 날짜 별칭 (사람이 정한 것, M2)
    tool_counts: Mapping[str, int] = field(default_factory=dict)
    looked_up: frozenset[str] = frozenset()                    # 영업시간 조회가 더는 새 정보를 못 주는 장소(조회했거나, 처음부터 다 안다)
    open_days_asked: frozenset[str] = frozenset()              # find_open_days를 이미 부른 장소(같은 답이라 되풀이를 거절한다)
    plan: tuple[str, ...] = ()
    lessons: tuple[str, ...] = ()

    def trial(self, trial_id: str) -> Optional[Trial]:
        return next((t for t in self.trials if t.trial_id == trial_id), None)


def initial_state(trip: Trip, hours: Hours, course: Optional[Course] = None) -> State:
    """course를 안 주면 초안 배치로 시작한다. 테스트는 정해진 코스로 시작할 수 있다."""
    course = course if course is not None else core.draft_course(trip)
    _check_course(trip, course)
    # 여행 날짜 전부의 휴무를 이미 아는 장소는 get_opening_hours가 새로 알려 줄 게 없다 — 처음부터 조회 끝으로 둔다.
    # 서비스에서는 시작 스냅샷이 DB의 휴무를 이미 담으므로, 스냅샷에 모르는 날이 남은 곳도 조회가 새 정보를 주지 못한다(같은 DB를 읽는다).
    # 그 경우는 첫 조회가 확인해 주므로 여기서는 "다 아는 곳"만 표시한다.
    known = frozenset(p.alias for p in trip.places if all(core.status_on(hours, p.alias, d) != "unknown" for d in trip.days))
    return State(
        trip=trip, hours=hours, course=course, looked_up=known,
        violations=core.find_violations(trip, course, hours),
        history=(Commit(0, course),),
    )


def with_hours(state: State, hours: Hours) -> State:
    """영업시간이 바뀌면 지금 코스와 살아 있는 시험의 위반을 다시 판정한다."""
    trip = state.trip
    return replace(
        state,
        hours=hours,
        violations=core.find_violations(trip, state.course, hours),
        trials=tuple(replace(t, violations=core.find_violations(trip, t.course, hours)) for t in state.trials),
    )


def _check_course(trip: Trip, course: Course) -> None:
    placed = [p for day in course for p in day]
    if len(course) != len(trip.days):
        raise ValueError("코스의 날짜 수가 여행 기간과 다르다")
    if sorted(placed) != sorted(p.alias for p in trip.places):
        raise ValueError("코스에 모든 장소가 정확히 한 번씩 있어야 한다")

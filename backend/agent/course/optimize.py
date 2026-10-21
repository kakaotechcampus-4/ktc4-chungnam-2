"""코스 최적화 — 강한 기준선을 끝까지 돌린다(pivot 3.2절). 순수 함수 + 영업시간 조회 포트만 쓴다.

모델의 `optimize` 도구가 부르고, 평가의 "강한 기준선" 방식도 같은 엔진이다. 한 수씩 시험·채택하는 도구 턴 상한(try_move 10 등)과
무관하게 더 나아지는 수가 없을 때까지(CLIMB_MAX_STEPS) 올라간다 — 비교할 때 "요청 목표를 아느냐"만 달라지게 하려는 것이다.
영업시간 조회는 기존 도구(get_opening_hours, 상한 6)를 그대로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Optional, Sequence

from agent.course import baseline, core, goals as goals_mod, tools
from agent.course.constants import CANDIDATES_MAX, CLIMB_MAX_STEPS, TOOL_LIMITS
from agent.course.goals import Goal
from agent.course.ports import OpeningHoursGateway
from agent.course.schemas import GetOpeningHours, MoveDay
from agent.course.state import Commit, State


@dataclass(frozen=True)
class Candidate:
    candidate_id: str                      # c1, c2 …
    course: core.Course
    violations: tuple[core.Violation, ...]
    priority: tuple[str, ...]              # 이 후보를 만든 목표 순서
    focus: Optional[str] = None            # 이 목표를 다른 목표보다 먼저 지킨 "집중" 후보(None이면 목표 수를 최대로 지킨 후보)


def look_up_unknowns(state: State, gateway: OpeningHoursGateway) -> State:
    """휴무를 모르는 장소를 도구 상한까지 조회한다(기존 get_opening_hours 규칙 그대로)."""
    for v in core.find_checks(state.trip, state.course, state.hours):
        place = v.places[0]
        if place in state.looked_up or state.tool_counts.get("get_opening_hours", 0) >= TOOL_LIMITS["get_opening_hours"]:
            continue
        state, _ = tools.execute(GetOpeningHours(tool="get_opening_hours", place=place), state, gateway)
    return state


def with_course(state: State, course: core.Course) -> State:
    return replace(
        state, course=course, violations=core.find_violations(state.trip, course, state.hours), trials=(),
        history=(*state.history, Commit(len(state.history), course)),
    )


def apply_locks(state: State, locks: Mapping[str, str]) -> State:
    """고정한 장소를 그 날로 옮긴다(이미 거기 있으면 그대로). 이후 수리는 고정을 어기지 못한다(core._check_lock)."""
    state = replace(state, locks={**state.locks, **locks})
    for place, day in sorted(state.locks.items()):
        frm, _ = core.locate(state.course, place)
        if core.day_alias(frm) == day:
            continue
        move = MoveDay(type="move_day", place=place, to_day=day, position=None)
        state = with_course(state, core.apply_move(state.trip, state.course, move, {}))
    return state


def climb(state: State) -> State:
    """더 나아지는 수가 없을 때까지 강한 기준선의 최선 수를 채택한다. 사전식 비교가 엄격히 좋아질 때만 채택하므로 끝난다."""
    for _ in range(CLIMB_MAX_STEPS):
        moves = baseline.strong_best_moves(state)
        if moves is None:
            break
        course = state.course
        for move in moves:
            course = core.apply_move(state.trip, course, move, state.locks)
        state = with_course(state, course)
    return state


def base_order(goals: Sequence[Goal], priority: Sequence[str]) -> tuple[str, ...]:
    ids = [g.id for g in goals]
    return tuple([i for i in priority if i in ids] + [i for i in ids if i not in priority])


def focus_order(base: Sequence[str], goal_id: str) -> tuple[str, ...]:
    """그 목표를 맨 앞에 두고 나머지는 원래 순서."""
    return (goal_id, *[i for i in base if i != goal_id])


def met_vector(state: State, course: core.Course) -> tuple:
    return tuple(r.met for r in goals_mod.evaluate_all(state.trip, course, state.goals))


def optimize(
    state: State, *, priority: Sequence[str] = (), locks: Optional[Mapping[str, str]] = None,
    gateway: OpeningHoursGateway,
) -> tuple[State, tuple[Candidate, ...]]:
    """(조회와 고정을 반영한 상태, 후보 1~3개). 후보는 목표가 서로 갈리게 만든다: 우선순위대로 목표 수를 최대로 지키는 후보 하나와,
    목표 하나를 맨 앞에 두고 다른 목표보다 먼저 지키는 "집중" 후보(우선순위 앞쪽 목표 순서로 최대 CANDIDATES_MAX-1개).
    목표별 met 벡터가 같은 후보는 합치고(먼저 만든 쪽을 남김), 시작보다 확정 위반이 늘어난 코스는 내지 않는다.
    상태의 course는 시작 코스 그대로다(후보를 고르는 것은 지휘 쪽) — 단 조회·고정 반영은 상태에 남는다."""
    start = apply_locks(look_up_unknowns(state, gateway), locks or {})
    ceiling = core.hard_score(start.violations)[0]
    base = base_order(start.goals, priority)
    runs: list[tuple[tuple[str, ...], bool, Optional[str]]] = [(base, False, None)]
    if len(start.goals) >= 2:
        runs += [(focus_order(base, gid), True, gid) for gid in base[: CANDIDATES_MAX - 1]]
    out: list[Candidate] = []
    seen: set[tuple] = set()
    for order, strict, focus in runs:
        done = climb(replace(start, priority=order, strict_priority=strict))
        vector = met_vector(start, done.course)
        if core.hard_score(done.violations)[0] > ceiling or vector in seen:
            continue
        seen.add(vector)
        out.append(Candidate(f"c{len(out) + 1}", done.course, done.violations, order, focus))
    if not out:                                   # 후보가 모두 걸러진 경우 — 시작 코스에서 한 번 올라간다
        done = climb(start)
        out.append(Candidate("c1", done.course, done.violations, ()))
    return replace(start, priority=tuple(priority), strict_priority=False), tuple(out)

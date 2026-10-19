"""코드 기준선(명세 10절) — 모델과 **같은 도구**를 정해진 규칙으로 쓴다. 순수 함수다.

쓰이는 곳: 모델이 쓸 수 없는 턴을 낸 때의 대행, 모델 호출 실패, 평가 비교 대상(명세 18절).
질문과 부드러운 목표 절충은 하지 않는다 — 그게 에이전트가 기준선보다 나아야 하는 지점이다.
"""

from __future__ import annotations

from typing import Optional

from agent.course import core
from agent.course.constants import TOOL_LIMITS
from agent.course.schemas import (
    CommitMove,
    Finish,
    GetOpeningHours,
    Move,
    MoveDay,
    Swap,
    ToolCall,
    TryMove,
)
from agent.course.state import State


def _key(state: State, course: core.Course, violations) -> tuple[int, int, int]:
    return (*core.hard_score(violations), core.course_travel(state.trip, course))


def _left(state: State, tool: str) -> bool:
    limit = TOOL_LIMITS.get(tool)
    return limit is None or state.tool_counts.get(tool, 0) < limit


def _best_move(state: State) -> Optional[Move]:
    """지금보다 나아지는 수리 중 가장 좋은 것. 위반에 걸린 장소만 건드린다. 같은 점수면 먼저 만든 수리."""
    targets = sorted({p for v in state.violations if v.status == "confirmed" for p in v.places})
    others = [p.alias for p in state.trip.places]
    candidates: list[Move] = []
    for p in targets:
        frm, _ = core.locate(state.course, p)
        candidates += [MoveDay(type="move_day", place=p, to_day=core.day_alias(i))
                       for i in range(len(state.trip.days)) if i != frm]
        candidates += [Swap(type="swap", a=p, b=q) for q in others if q != p]

    current = _key(state, state.course, state.violations)
    best: tuple[tuple[int, int, int], Optional[Move]] = (current, None)
    for move in candidates:
        try:
            course = core.apply_move(state.trip, state.course, move, state.locks)
        except core.MoveError:
            continue
        key = _key(state, course, core.find_violations(state.trip, course, state.hours))
        if key < best[0]:
            best = (key, move)
    return best[1]


def next_action(state: State) -> ToolCall:
    # 1. 모르는 영업시간부터 조회한다
    unknown = [v.places[0] for v in core.find_checks(state.trip, state.course, state.hours)
               if v.places[0] not in state.looked_up]
    if unknown and _left(state, "get_opening_hours"):
        return GetOpeningHours(tool="get_opening_hours", place=unknown[0])

    # 2. 지금보다 나은 시험이 있으면 채택한다
    current = _key(state, state.course, state.violations)
    better = [t for t in state.trials if _key(state, t.course, t.violations) < current]
    if better:
        best = min(better, key=lambda t: _key(state, t.course, t.violations))
        return CommitMove(tool="commit_move", trial_id=best.trial_id)

    # 3. 나아지는 수리를 찾아 시험한다
    if _left(state, "try_move"):
        move = _best_move(state)
        if move is not None:
            return TryMove(tool="try_move", move=move)

    confirmed, _ = core.hard_score(state.violations)
    return Finish(tool="finish", reason_code="solved" if confirmed == 0 else "no_progress")

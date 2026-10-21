"""코드 기준선(명세 10절) — 모델과 **같은 도구**를 정해진 규칙으로 쓴다. 순수 함수다.

쓰이는 곳: 모델이 쓸 수 없는 턴을 낸 때의 대행, 모델 호출 실패, 평가 비교 대상(명세 18절).
질문과 부드러운 목표 절충은 하지 않는다 — 그게 에이전트가 기준선보다 나아야 하는 지점이다.
"""

from __future__ import annotations

from typing import Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.constants import TOOL_LIMITS
from agent.course.schemas import (
    CommitMove,
    Finish,
    GetOpeningHours,
    Move,
    MoveDay,
    ReorderDay,
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


# ---- 강한 기준선 ----
# 위반을 먼저 줄이고, 위반이 없어지면 날짜 균형, 대중교통 구간 수(하루에 한 지역)와 기본 목표(식당 연속·하루 식당 수·식사 후 카페·야경 마지막·카테고리 섞기·날짜 균형)를 욕심껏 줄인다.
# 같은 도구·같은 상한으로 움직인다. 모델이 있어야 하는 판단(사람의 말을 목표로 바꾸기, 목표끼리의 절충 설명)은 못 한다.

def _soft_key(trip, course) -> tuple[float, ...]:
    s = core.soft_scores(trip, course)
    return (
        s["day_balance"],                        # 날 사이 장소 수가 고른 것이 먼저(위반·요청 목표 다음)
        s["transit_legs"],                       # 그다음 하루에 한 지역: 대중교통 구간이 적을수록 좋다(식사 같은 기본 목표보다 먼저)
        s["meal_spacing"] + s["meal_per_day"] + s["cafe_spacing"],
        -(s["cafe_after_meal"] or 0.0),
        -(s["night_last"] or 0.0),
        s["mono_category_days"] + (s["no_tour_days"] or 0),
        s["travel_total"],
    )


def strong_key(state: State, course: core.Course, violations) -> tuple:
    # 확정 위반 → 확인 필요 → 요청 목표(충족 수, 우선순위순) → 기본 목표. 요청 목표가 없으면 이 자리는 빈 값이다
    return (*core.hard_score(violations), goals_mod.key_part(state.trip, course, state.goals, state.priority, state.strict_priority),
            _soft_key(state.trip, course))


def _walk_days(state: State) -> list[int]:
    """도보(구간·하루·구성원) 위반이 걸린 날의 위치."""
    days = {core.day_index(state.trip, v.day) for v in state.violations if v.status == "confirmed" and v.kind in ("travel", "member")}
    return sorted(i for i in days if i is not None)


def _reorder_moves(state: State, course: core.Course, days: Sequence[int]) -> list[Move]:
    """그 날들의 방문 순서를 구간 초과가 없고 짧게 다시 짠 수. 이미 가장 좋은 순서인 날은 뺀다."""
    out: list[Move] = []
    for i in dict.fromkeys(days):
        order = core.best_day_order(state.trip, course[i])
        if order != tuple(course[i]):
            out.append(ReorderDay(type="reorder_day", day=core.day_alias(i), places=list(order)))
    return out


def _apply_all(state: State, moves: Sequence[Move]) -> core.Course:
    course = state.course
    for move in moves:
        course = core.apply_move(state.trip, course, move, state.locks)
    return course


def strong_best_moves(state: State, *, bundles: bool = True) -> Optional[tuple[Move, ...]]:
    """지금보다 엄격히 나아지는 수(또는 수 묶음) 중 가장 좋은 것. 같은 점수면 먼저 만든 쪽.
    수 하나: 날 옮기기·맞바꾸기·같은 날 안에서 자리 옮기기. 도보 위반이 남아 있으면 거기에 더해
    - 위반이 걸린 날의 순서 다시 짜기(reorder_day),
    - (bundles=True일 때) 위반에 걸린 장소의 날 옮기기·맞바꾸기 뒤 닿은 두 날의 순서를 다시 짜는 묶음(옮기기만으로는 자리가 안 맞아 못 고치는 위반을 푼다).
    묶음은 앞의 수가 혼자서는 나아지지 않아도 된다 — 묶음 전체가 엄격히 나아질 때만 채택한다. 확정 위반이 늘어나는 수는 고르지 않는다."""
    places = [p.alias for p in state.trip.places]
    n_days = len(state.trip.days)
    candidates: list[tuple[Move, ...]] = []
    for p in places:
        frm, _ = core.locate(state.course, p)
        candidates += [(MoveDay(type="move_day", place=p, to_day=core.day_alias(i)),) for i in range(n_days) if i != frm]
        candidates += [(Swap(type="swap", a=p, b=q),) for q in places if q > p]
    for i, day in enumerate(state.course):                    # 같은 날 안에서 장소 하나의 자리를 옮기기(야경을 마지막으로 같은 목표)
        for k, p in enumerate(day):
            rest = [*day[:k], *day[k + 1:]]
            candidates += [(ReorderDay(type="reorder_day", day=core.day_alias(i), places=[*rest[:pos], p, *rest[pos:]]),)
                           for pos in range(len(day)) if pos != k]
    walk_days = _walk_days(state)
    candidates += [(m,) for m in _reorder_moves(state, state.course, walk_days)]
    if walk_days and bundles:
        targets = sorted({p for v in state.violations if v.status == "confirmed" and v.kind in ("travel", "member") for p in v.places})
        for p in targets:
            frm, _ = core.locate(state.course, p)
            firsts: list[Move] = [MoveDay(type="move_day", place=p, to_day=core.day_alias(i)) for i in range(n_days) if i != frm]
            firsts += [Swap(type="swap", a=p, b=q) for q in places if q != p]
            for first in firsts:
                try:
                    moved = core.apply_move(state.trip, state.course, first, state.locks)
                except core.MoveError:
                    continue
                touched = [i for i, (old, new) in enumerate(zip(state.course, moved)) if old != new]
                follow = _reorder_moves(state, moved, touched)
                if follow:
                    candidates.append((first, *follow))
    best: tuple[tuple, Optional[tuple[Move, ...]]] = (strong_key(state, state.course, state.violations), None)
    for moves in candidates:
        try:
            course = _apply_all(state, moves)
        except core.MoveError:
            continue
        key = strong_key(state, course, core.find_violations(state.trip, course, state.hours))
        if key < best[0]:
            best = (key, moves)
    return best[1]


def strong_best_move(state: State) -> Optional[Move]:
    """수 하나만(묶음 없이) 쓰는 정책용. 한 번에 한 수씩 시험하는 도구 루프(next_action_strong)가 쓴다."""
    moves = strong_best_moves(state, bundles=False)
    return moves[0] if moves else None


def next_action_strong(state: State) -> ToolCall:
    unknown = [v.places[0] for v in core.find_checks(state.trip, state.course, state.hours)
               if v.places[0] not in state.looked_up]
    if unknown and _left(state, "get_opening_hours"):
        return GetOpeningHours(tool="get_opening_hours", place=unknown[0])

    current = strong_key(state, state.course, state.violations)
    better = [t for t in state.trials if strong_key(state, t.course, t.violations) < current]
    if better:
        best = min(better, key=lambda t: strong_key(state, t.course, t.violations))
        return CommitMove(tool="commit_move", trial_id=best.trial_id)

    if _left(state, "try_move"):
        move = strong_best_move(state)
        if move is not None:
            return TryMove(tool="try_move", move=move)

    confirmed, _ = core.hard_score(state.violations)
    return Finish(tool="finish", reason_code="solved" if confirmed == 0 else "no_progress")

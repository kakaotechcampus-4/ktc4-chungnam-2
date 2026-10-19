"""도구 실행(명세 7절). 매개변수 검사 → 실행 → 결과 또는 구조화된 오류.

오류는 예외로 올리지 않고 ToolResult(ok=False)로 돌려준다 — 모델이 그 오류를 보고 다시 계획하는 것이
에이전트 루프의 일부다. 결과에는 별칭과 코드가 판정한 값만 담는다(좌표·id·이름은 넣지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from agent.course import core
from agent.course.constants import MAX_LIVE_TRIALS, TOOL_LIMITS
from agent.course.ports import OpeningHoursGateway
from agent.course.schemas import (
    CommitMove,
    EstimateTravel,
    FindOpenDays,
    Finish,
    GetOpeningHours,
    Revert,
    ToolCall,
    TryMove,
)
from agent.course.state import Commit, State, Trial, with_hours


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    data: Optional[Mapping[str, Any]] = None
    error: Optional[str] = None       # INVALID_ID | INVALID_MOVE | ALREADY_LOOKED_UP | LOCKED | WORSENS_HARD | LIMIT_EXCEEDED | NO_SUCH_TRIAL
    message: Optional[str] = None

    def as_input(self) -> dict[str, Any]:
        """다음 턴 모델 입력에 넣는 모양."""
        out: dict[str, Any] = {"tool": self.tool, "ok": self.ok}
        if self.ok:
            out["data"] = dict(self.data or {})
        else:
            out["error"] = self.error
            out["message"] = self.message
        return out


def _fail(tool: str, code: str, message: str) -> ToolResult:
    return ToolResult(tool, ok=False, error=code, message=message)


def _days_of(state: State, place: str) -> dict[str, str]:
    return {core.day_alias(i): core.status_on(state.hours, place, d) for i, d in enumerate(state.trip.days)}


def _cached(tool: str, place: str, state: State, data: Mapping[str, Any]) -> ToolResult:
    return ToolResult(tool, ok=True, data={"place": place, **data, "memo": "이미 조회한 결과"})


def _hard(state: State, course: core.Course, violations) -> dict[str, int]:
    return core.hard_summary(state.trip, state.hours, course, violations)


def execute(call: ToolCall, state: State, hours_gateway: OpeningHoursGateway) -> tuple[State, ToolResult]:
    tool = call.tool
    # 같은 정보를 다시 물으면 거절하지 않고 저장된 답을 돌려준다 — 모델은 매 턴 직전 결과만 보므로 이전 답을 잊고 되묻는다.
    # 횟수는 쓰지 않는다. 서비스에서는 시작 스냅샷이 DB 휴무를 이미 담으므로 get_opening_hours가 새 정보를 줄 수 없다(같은 DB를 읽는다).
    # 시작 때 휴무를 다 아는 곳은 state.initial_state가 처음부터 looked_up에 넣는다.
    if isinstance(call, GetOpeningHours) and call.place in state.looked_up:
        return state, _cached(tool, call.place, state, {
            "days": _days_of(state, call.place), "resolved_unknown": 0, "hard": _hard(state, state.course, state.violations),
        })
    if isinstance(call, FindOpenDays) and call.place in state.open_days_asked and state.trip.has_place(call.place):
        return state, _cached(tool, call.place, state, core.open_days(state.trip, state.hours, call.place))
    limit = TOOL_LIMITS.get(tool)
    if limit is not None and state.tool_counts.get(tool, 0) >= limit:
        return state, _fail(tool, "LIMIT_EXCEEDED", f"{tool}는 이번 코스에서 {limit}번까지 쓸 수 있다")
    state = replace(state, tool_counts={**state.tool_counts, tool: state.tool_counts.get(tool, 0) + 1})

    if isinstance(call, GetOpeningHours):
        return _get_opening_hours(call, state, hours_gateway)
    if isinstance(call, FindOpenDays):
        if not state.trip.has_place(call.place):
            return state, _fail(tool, "INVALID_ID", f"{call.place}는 없는 장소다")
        state = replace(state, open_days_asked=state.open_days_asked | {call.place})
        return state, ToolResult(tool, ok=True, data={"place": call.place, **core.open_days(state.trip, state.hours, call.place)})
    if isinstance(call, EstimateTravel):
        for p in (call.from_place, call.to_place):
            if not state.trip.has_place(p):
                return state, _fail(tool, "INVALID_ID", f"{p}는 없는 장소다")
        minutes = core.travel_minutes(state.trip, call.from_place, call.to_place)
        return state, ToolResult(tool, ok=True, data={"from": call.from_place, "to": call.to_place, "walk_minutes": minutes})
    if isinstance(call, TryMove):
        return _try_move(call, state)
    if isinstance(call, CommitMove):
        return _commit(call, state)
    if isinstance(call, Revert):
        return _revert(call, state)
    if isinstance(call, Finish):
        return state, ToolResult(tool, ok=True, data={"reason_code": call.reason_code})
    raise TypeError(f"실행할 수 없는 도구 {type(call).__name__}")   # 스키마가 막는다. 도구를 추가하고 여기를 빠뜨린 경우


def _get_opening_hours(call: GetOpeningHours, state: State, gateway: OpeningHoursGateway) -> tuple[State, ToolResult]:
    if not state.trip.has_place(call.place):
        return state, _fail(call.tool, "INVALID_ID", f"{call.place}는 없는 장소다")
    place = state.trip.place(call.place)
    found = gateway.get_opening_hours([place.place_id]).get(place.place_id)
    unknown_before = len(core.find_checks(state.trip, state.course, state.hours))
    # 조회 결과에 없는 요일은 이전 값을 그대로 둔다. 모르는 값으로 아는 값을 덮지 않는다.
    merged = {**state.hours.get(call.place, {}), **{wd: s for wd, s in (found or {}).items() if s != "unknown"}}
    new_state = with_hours(replace(state, looked_up=state.looked_up | {call.place}), {**state.hours, call.place: merged})
    days = _days_of(new_state, call.place)
    return new_state, ToolResult(call.tool, ok=True, data={
        "place": call.place,
        "days": days,
        "resolved_unknown": unknown_before - len(core.find_checks(new_state.trip, new_state.course, new_state.hours)),
        "hard": _hard(new_state, new_state.course, new_state.violations),
    })


def _try_move(call: TryMove, state: State) -> tuple[State, ToolResult]:
    if len(state.trials) >= MAX_LIVE_TRIALS:
        return state, _fail(call.tool, "LIMIT_EXCEEDED",
                            f"채택하지 않은 시험은 {MAX_LIVE_TRIALS}개까지다 — 하나를 채택하거나 다른 수리로 넘어간다")
    try:
        course = core.apply_move(state.trip, state.course, call.move, state.locks)
    except core.MoveError as exc:
        return state, _fail(call.tool, exc.code, str(exc))
    violations = core.find_violations(state.trip, course, state.hours)
    trial = Trial(f"t{state.trial_seq + 1}", call.move, course, violations)
    before_ids = {v.id for v in state.violations}
    after_ids = {v.id for v in violations}
    return replace(state, trials=(*state.trials, trial), trial_seq=state.trial_seq + 1), ToolResult(call.tool, ok=True, data={
        "trial_id": trial.trial_id,
        "hard_before": _hard(state, state.course, state.violations),
        "hard_after": _hard(state, course, violations),
        "soft_before": core.soft_scores(state.trip, state.course),
        "soft_after": core.soft_scores(state.trip, course),
        "resolved": sorted(before_ids - after_ids),
        "appeared": sorted(after_ids - before_ids),
    })


def _commit(call: CommitMove, state: State) -> tuple[State, ToolResult]:
    trial = state.trial(call.trial_id)
    if trial is None:
        return state, _fail(call.tool, "NO_SUCH_TRIAL", f"{call.trial_id}는 살아 있는 시험이 아니다")
    if core.hard_score(trial.violations)[0] > core.hard_score(state.violations)[0]:
        # 하드 확정 위반을 늘리는 채택은 거부한다(명세 3절 3번). 결측·부드러운 목표의 절충은 모델 판단이다.
        return state, _fail(call.tool, "WORSENS_HARD", "확정 위반이 늘어나는 수리는 채택할 수 없다")
    step = len(state.history)
    # 채택하면 남은 시험은 버린다 — 이전 코스 위에서 만든 시험이라 지금 코스에 맞지 않는다.
    new_state = replace(state, course=trial.course, violations=trial.violations, trials=(),
                        history=(*state.history, Commit(step, trial.course)))
    return new_state, ToolResult(call.tool, ok=True, data={"step": step, "hard": _hard(new_state, new_state.course, new_state.violations)})


def _revert(call: Revert, state: State) -> tuple[State, ToolResult]:
    if not 0 <= call.to_step < len(state.history):
        return state, _fail(call.tool, "INVALID_ID", f"채택 단계 {call.to_step}는 없다")
    course = state.history[call.to_step].course
    step = len(state.history)
    new_state = replace(state, course=course, violations=core.find_violations(state.trip, course, state.hours),
                        trials=(), history=(*state.history, Commit(step, course)))
    return new_state, ToolResult(call.tool, ok=True, data={"step": step, "hard": _hard(new_state, new_state.course, new_state.violations)})

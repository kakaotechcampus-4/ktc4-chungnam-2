"""에이전트 루프(명세 11절). 순서와 상한만 정한다 — 판단은 core·tools·baseline에 있다.

모델 자리는 `decide`로 주입한다. M1에서 `llm.api`의 턴 함수를 감싸 넣는다. `decide=None`이면 기준선이 끝까지 돈다.
DB 저장(매 턴 상태 저장, 질문 뒤 재개)은 M1에서 이 루프 바깥(flows.py)이 맡는다 — 여기서는 세션을 열지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from pydantic import ValidationError

from agent.course import baseline, core, tools
from agent.course.constants import (
    LESSONS_KEEP, MAX_INVALID_TURNS, MAX_TURNS, PLAN_MAX_STEPS, RUN_TIMEOUT_SEC, TOOL_LIMITS,
)
from agent.course.ports import OpeningHoursGateway
from agent.course.schemas import AgentTurn, Finish
from agent.course.state import State
from agent.course.tools import ToolResult

# 모델 자리. 턴 입력(dict)을 받아 AgentTurn을 돌려준다. 실패하면 예외를 올린다.
Decide = Callable[[dict[str, Any]], AgentTurn]

# 모델 쪽 실패로 보고 그 턴을 기준선에 넘기는 예외들. llm.client.LlmCallError는 RuntimeError다.
# 그 밖의 예외(코드 버그)는 삼키지 않고 그대로 올린다(docs/code-quality.md "실패를 감추지 않는다").
MODEL_FAILURES = (ValidationError, RuntimeError, TimeoutError)

# 모델에게 새로 알려 주는 게 없는 오류. 이 오류가 나면 그 턴은 기준선이 대신 둔다. (그 밖의 오류는 메시지가 계획에 도움이 된다)
UNUSABLE_ERRORS = ("ALREADY_LOOKED_UP", "LIMIT_EXCEEDED")


@dataclass(frozen=True)
class Step:
    """시도 기록 한 줄(명세 15.2 steps). thought는 검증을 통과해 렌더한 문장이고, 통과하지 못하면 None이다."""
    turn: int
    by: str                    # model | baseline
    thought: Optional[str]
    thought_problem: Optional[str]
    call: dict[str, Any]
    result: ToolResult
    repeated: bool = False     # 직전과 같은 호출이라 실행하지 않고 직전 결과를 돌려준 경우
    substituted_for: Optional[dict[str, Any]] = None   # 모델의 호출이 쓸 수 없어 기준선이 대신한 경우 {"call", "error"}


@dataclass(frozen=True)
class RunResult:
    outcome: str
    best_course: core.Course
    best_violations: tuple[core.Violation, ...]
    soft: dict[str, Any]
    steps: tuple[Step, ...]
    state: State
    model_turns: int
    baseline_turns: int


def _open_closed(state: State, place: str) -> dict[str, list[str]]:
    """코드가 이미 아는 영업 정보 — 모델이 find_open_days로 되묻지 않아도 된다. 둘 다 아닌 날은 모르는 날이다."""
    days = core.open_days(state.trip, state.hours, place)
    return {"open_days": days["open"], "closed_days": days["closed"]}


def turn_input(state: State, last: Optional[ToolResult], turn: int) -> dict[str, Any]:
    """모델에 보내는 한 턴의 입력(명세 11.1). 매 턴 상태로 새로 만든다 — 대화 기록을 쌓지 않는다.
    별칭만 넣는다: pin_id, place_id, 좌표, 장소 이름, 구성원 이름은 넣지 않는다(명세 3절 5번)."""
    trip = state.trip
    return {
        "turn": turn,
        "goal": "하드 위반을 0으로, 그다음 부드러운 목표를 좋게",
        "mode": "B",
        "days": [
            {
                "day": core.day_alias(i),
                "weekday": "월화수목금토일"[d.weekday()],
                "places": [
                    {"place": p, "category": trip.place(p).category, "labels": sorted(trip.place(p).labels),
                     **_open_closed(state, p)}
                    for p in state.course[i]
                ],
            }
            for i, d in enumerate(trip.days)
        ],
        "violations": [
            {"id": v.id, "kind": v.kind, "status": v.status, "places": list(v.places), **dict(v.detail)}
            for v in state.violations
        ],
        **({"checks": [{"id": v.id, "place": v.places[0], "day": v.day, "looked_up": v.places[0] in state.looked_up}
                       for v in core.find_checks(trip, state.course, state.hours)]}
           if trip.unknown_hours == "check" else {}),
        "soft": core.soft_scores(trip, state.course),
        "locks": [{"place": p, "day": d} for p, d in sorted(state.locks.items())],
        "live_trials": [
            {"trial_id": t.trial_id, "move": t.move.model_dump(),
             "hard": core.hard_summary(trip, state.hours, t.course, t.violations)}
            for t in state.trials
        ],
        "history_steps": len(state.history),
        "plan": list(state.plan),
        "lessons": list(state.lessons),
        "last_result": last.as_input() if last else None,
        "budget": {
            "turns_left": MAX_TURNS - turn + 1,
            **{f"{tool}_left": limit - state.tool_counts.get(tool, 0) for tool, limit in TOOL_LIMITS.items()},
        },
    }


def _best(state: State, best: tuple[core.Course, tuple[core.Violation, ...]]):
    # 하드 점수가 같으면 나중 상태를 고른다 — 부드러운 목표 절충은 모델의 판단을 존중한다(명세 11.3).
    if core.hard_score(state.violations) <= core.hard_score(best[1]):
        return state.course, state.violations
    return best


def run_loop(
    state: State,
    *,
    decide: Optional[Decide],
    hours: OpeningHoursGateway,
    policy: Callable[[State], Any] = baseline.next_action,   # 모델이 없거나 실패한 턴을 맡는 규칙(기본: 기준선, 평가는 강한 기준선)
    clock: Callable[[], float] = time.monotonic,
) -> RunResult:
    started = clock()
    driver = "model" if decide is not None else "baseline"
    invalid_streak = 0
    steps: list[Step] = []
    last: Optional[ToolResult] = None
    best = (state.course, state.violations)
    timed_out = False

    for turn in range(1, MAX_TURNS + 1):
        if clock() - started > RUN_TIMEOUT_SEC:
            timed_out = True
            break

        thought = problem = None
        if driver == "model":
            try:
                agent_turn = decide(turn_input(state, last, turn))
                call, by = agent_turn.action, "model"
                invalid_streak = 0
                problem = core.thought_problem(state.trip, agent_turn.thought)
                thought = None if problem else core.render_thought(state.trip, agent_turn.thought)
                lessons = state.lessons + ((agent_turn.lesson,) if agent_turn.lesson else ())
                state = replace(state, plan=tuple(s.intent for s in agent_turn.plan[:PLAN_MAX_STEPS]), lessons=lessons[-LESSONS_KEEP:])
            except MODEL_FAILURES:
                invalid_streak += 1
                if invalid_streak >= MAX_INVALID_TURNS:
                    driver = "baseline"   # 이후 모델을 부르지 않는다
                call, by = policy(state), "baseline"
        else:
            call, by = policy(state), "baseline"

        call_dump = call.model_dump()
        substituted = None
        if steps and steps[-1].call == call_dump and call.tool != "finish":
            # 같은 호출을 연달아 하면 실행하지 않고 직전 결과를 돌려준다 — 헛도는 루프 방지(명세 11.2).
            result, repeated = steps[-1].result, True
        else:
            state, result = tools.execute(call, state, hours)
            repeated = False
            if by == "model" and not result.ok and result.error in UNUSABLE_ERRORS:
                # 정보 없는 거절로 턴을 버리지 않는다 — 그 턴은 기준선이 한 수를 둔다(실패한 호출은 상태를 안 바꿨다).
                substituted = {"call": call_dump, "error": result.error}
                call, by, thought, problem = policy(state), "baseline", None, None
                call_dump = call.model_dump()
                state, result = tools.execute(call, state, hours)
        steps.append(Step(turn, by, thought, problem, call_dump, result, repeated, substituted))
        last = result
        best = _best(state, best)
        if isinstance(call, Finish):
            break

    return RunResult(
        outcome=core.outcome(
            best[1], timed_out=timed_out, checks=len(core.find_checks(state.trip, best[0], state.hours)),
        ),
        best_course=best[0],
        best_violations=best[1],
        soft=core.soft_scores(state.trip, best[0]),
        steps=tuple(steps),
        state=state,
        model_turns=sum(s.by == "model" for s in steps),
        baseline_turns=sum(s.by == "baseline" for s in steps),
    )

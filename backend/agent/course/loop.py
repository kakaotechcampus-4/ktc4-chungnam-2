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
from agent.course.constants import LESSONS_KEEP, MAX_INVALID_TURNS, MAX_TURNS, RUN_TIMEOUT_SEC, TOOL_LIMITS
from agent.course.ports import OpeningHoursGateway
from agent.course.schemas import AgentTurn, Finish
from agent.course.state import State
from agent.course.tools import ToolResult

# 모델 자리. 턴 입력(dict)을 받아 AgentTurn을 돌려준다. 실패하면 예외를 올린다.
Decide = Callable[[dict[str, Any]], AgentTurn]

# 모델 쪽 실패로 보고 그 턴을 기준선에 넘기는 예외들. llm.client.LlmCallError는 RuntimeError다.
# 그 밖의 예외(코드 버그)는 삼키지 않고 그대로 올린다(docs/code-quality.md "실패를 감추지 않는다").
MODEL_FAILURES = (ValidationError, RuntimeError, TimeoutError)


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


def turn_input(state: State, last: Optional[ToolResult], turns_left: int) -> dict[str, Any]:
    """모델에 보내는 한 턴의 입력(명세 11.1). 매 턴 상태로 새로 만든다 — 대화 기록을 쌓지 않는다.
    별칭만 넣는다: pin_id, place_id, 좌표, 장소 이름, 구성원 이름은 넣지 않는다(명세 3절 5번)."""
    trip = state.trip
    return {
        "goal": "하드 위반을 0으로, 그다음 부드러운 목표를 좋게",
        "mode": "B",
        "days": [
            {
                "day": core.day_alias(i),
                "weekday": "월화수목금토일"[d.weekday()],
                "places": [
                    {"place": p, "category": trip.place(p).category, "labels": sorted(trip.place(p).labels)}
                    for p in state.course[i]
                ],
            }
            for i, d in enumerate(trip.days)
        ],
        "violations": [
            {"id": v.id, "kind": v.kind, "status": v.status, "places": list(v.places), **dict(v.detail)}
            for v in state.violations
        ],
        "soft": core.soft_scores(trip, state.course),
        "locks": [{"place": p, "day": d} for p, d in sorted(state.locks.items())],
        "live_trials": [
            {"trial_id": t.trial_id, "move": t.move.model_dump(),
             "hard": dict(zip(("confirmed", "unknown"), core.hard_score(t.violations)))}
            for t in state.trials
        ],
        "history_steps": len(state.history),
        "plan": list(state.plan),
        "lessons": list(state.lessons),
        "last_result": last.as_input() if last else None,
        "budget": {
            "turns_left": turns_left,
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
                agent_turn = decide(turn_input(state, last, MAX_TURNS - turn + 1))
                call, by = agent_turn.action, "model"
                invalid_streak = 0
                problem = core.thought_problem(state.trip, agent_turn.thought)
                thought = None if problem else core.render_thought(state.trip, agent_turn.thought)
                lessons = state.lessons + ((agent_turn.lesson,) if agent_turn.lesson else ())
                state = replace(state, plan=tuple(s.intent for s in agent_turn.plan), lessons=lessons[-LESSONS_KEEP:])
            except MODEL_FAILURES:
                invalid_streak += 1
                if invalid_streak >= MAX_INVALID_TURNS:
                    driver = "baseline"   # 이후 모델을 부르지 않는다
                call, by = baseline.next_action(state), "baseline"
        else:
            call, by = baseline.next_action(state), "baseline"

        call_dump = call.model_dump()
        if steps and steps[-1].call == call_dump and call.tool != "finish":
            # 같은 호출을 연달아 하면 실행하지 않고 직전 결과를 돌려준다 — 헛도는 루프 방지(명세 11.2).
            result, repeated = steps[-1].result, True
        else:
            state, result = tools.execute(call, state, hours)
            repeated = False
        steps.append(Step(turn, by, thought, problem, call_dump, result, repeated))
        last = result
        best = _best(state, best)
        if isinstance(call, Finish):
            break

    return RunResult(
        outcome=core.outcome(best[1], timed_out=timed_out),
        best_course=best[0],
        best_violations=best[1],
        soft=core.soft_scores(state.trip, best[0]),
        steps=tuple(steps),
        state=state,
        model_turns=sum(s.by == "model" for s in steps),
        baseline_turns=sum(s.by == "baseline" for s in steps),
    )

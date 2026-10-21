"""요청 한 줄 → 목표 세우기 → 지휘 루프 → 화면용 결과. 엔진을 서비스 경로에 한 번 묶는 곳이다(eval/demo.py의 run_direct_demo와 같은 순서).

DB를 모른다. 모델 자리는 planner로 주입한다(llm.api의 fixed/real planner 또는 테스트 대역). 그래서 서비스는 읽기 → 롤백 →
이 함수(모델) → 쓰기 순서(backend/CLAUDE.md "모델 호출과 트랜잭션")를 지킬 수 있다.

- 질문(ask_requester)에는 답을 받지 않는다. 엔진이 답이 없으면 기본값으로 이어 간다 — 이 경로에는 대기 상태가 없다.
- 요청 한 줄이 없으면 모델을 부르지 않는다(목표 0개 → 지휘 루프도 모델 없이 한 번 최적화). 목표 세우기가 실패하면 요청 전체가
  "반영하지 못했어요"로 남고 코스는 기본 목표로 짠다.
- 영업시간은 `OpeningHoursGateway`로 읽는다. 시작 스냅샷도 같은 게이트웨이에서 만든다(`start_hours`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from agent.course import core, direct, goals as goals_mod, worklog
from agent.course.constants import REQUEST_TEXT_MAX_CHARS
from agent.course.deps import DirectDecider, GoalSetter, ModelTurnFailed
from agent.course.intake import TripBuild
from agent.course.ports import OpeningHoursGateway
from agent.course.result import CourseView, build_view
from agent.course.state import initial_state

log = logging.getLogger("pingo.agent.course")

OnStepRecord = Callable[[worklog.StepRecord], None]


@dataclass(frozen=True)
class Computation:
    view: CourseView
    model_turns: int
    tokens_in: int
    tokens_out: int
    model: Optional[str]
    prompt_version: Optional[str]


def start_hours(trip: core.Trip, gateway: OpeningHoursGateway) -> dict[str, dict[int, core.DayStatus]]:
    """시작 스냅샷이 아는 영업시간 — 장소 별칭 → 요일 → 상태. 모르는 장소는 칸이 없다(모름)."""
    found = gateway.get_opening_hours([p.place_id for p in trip.places])
    return {p.alias: dict(found[p.place_id]) for p in trip.places if found.get(p.place_id)}


def _usage_meta(*metered: Any) -> tuple[Optional[str], Optional[str]]:
    usages = [u for m in metered if m is not None for u in m.usages]
    models = list(dict.fromkeys(u.model for u in usages if u.model))
    versions = list(dict.fromkeys(u.prompt_version for u in usages if u.prompt_version))
    return (", ".join(models) or None), (", ".join(versions) or None)


def run_course(
    build: TripBuild, request_text: str, *,
    goals_planner: Optional[Callable[[Mapping[str, Any]], Any]],
    direct_planner: Optional[Callable[[Mapping[str, Any]], Any]],
    gateway: OpeningHoursGateway, on_step: Optional[OnStepRecord] = None,
) -> Computation:
    """build.trip이 있어야 한다(too_few면 호출하지 않는다). 모델 호출 실패는 던지지 않는다 — 기준선이 대신한다.

    on_step(record)는 작업 기록 단계(`worklog.StepRecord`)가 생길 때마다 순서대로 부른다: 목표 세우기 뒤의 "이해", 확인 문장, 지휘 턴마다의
    생각·도구 결과·검증 줄·기본값 답, 마지막 "결과". 콜백이 던져도 계산은 계속한다(진행 표시는 부가 기능이다)."""
    trip = build.trip
    assert trip is not None
    text = request_text.strip()[:REQUEST_TEXT_MAX_CHARS]
    setter = GoalSetter(goals_planner) if goals_planner is not None and text else None
    decider = DirectDecider(direct_planner) if direct_planner is not None else None
    goals: tuple[goals_mod.Goal, ...] = ()
    unmatched: tuple[str, ...] = ()
    understood_by = worklog.MODEL
    if text:
        if setter is None:                       # 목표를 세울 모델 자리가 없다 — 요청 전체를 반영하지 못했다고 밝힌다
            unmatched, understood_by = (text,), "코드(목표 세우기 없음)"
        else:
            try:
                verified = goals_mod.verify_goal_set(trip, text, setter(goals_mod.goals_input(trip, text)))
                goals, unmatched = verified.goals, verified.unmatched
            except ModelTurnFailed:
                unmatched, understood_by = (text,), "코드(목표 세우기 실패)"

    def emit(recs: list[worklog.StepRecord]) -> None:
        for rec in recs:
            if on_step is None:
                continue
            try:
                on_step(rec)
            except Exception as exc:   # noqa: BLE001 — 진행 저장 실패가 코스 계산을 멈추면 안 된다. 클래스 이름만 로그
                log.warning("course 진행 기록 실패: %s", type(exc).__name__)

    narrator = worklog.Narrator(trip, goals, unmatched, understood_by=understood_by)
    records = narrator.opening()
    emit(records)

    def on_direct_step(step: direct.DirectStep, ds: direct.DirectState) -> None:
        new = narrator.step(step, goals=ds.state.goals, questions=ds.questions)
        records.extend(new)
        emit(new)

    state = initial_state(trip, start_hours(trip, gateway), core.draft_course(trip), goals)
    result = direct.run_direct(state, decide=decider, hours=gateway, unmatched_count=len(unmatched),
                              on_step=on_direct_step)
    closing = narrator.closing(result)
    records.extend(closing)
    emit(closing)
    model, prompt_version = _usage_meta(setter, decider)
    tokens = [m.tokens for m in (setter, decider) if m is not None]
    return Computation(
        view=build_view(trip, build.excluded, goals, unmatched, result, records),
        model_turns=result.model_turns,
        tokens_in=sum(t[0] for t in tokens), tokens_out=sum(t[1] for t in tokens),
        model=model, prompt_version=prompt_version,
    )

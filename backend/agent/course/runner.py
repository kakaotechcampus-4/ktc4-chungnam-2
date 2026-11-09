"""요청 한 줄 → 목표 세우기 → 지휘 루프 → 화면용 결과. 엔진을 서비스 경로에 한 번 묶는 곳이다(eval/demo.py의 run_direct_demo와 같은 순서).

DB를 모른다. 모델 자리는 planner로 주입한다(llm.api의 fixed/real planner 또는 테스트 대역). 그래서 서비스는 읽기 → 롤백 →
이 함수(모델) → 쓰기 순서(backend/CLAUDE.md "모델 호출과 트랜잭션")를 지킬 수 있다.

- 요청자에게 되묻지 않는다(#1131). 쉬는 날·이동이 넘치는 날은 엔진이 도구로 확인해 정하고, 모르는 영업시간은 가정 줄로 남긴다 — 대기 상태가 없다.
- 요청 한 줄이 없어도 지도 목표 후보(우리 조건 요약·장소 라벨, #1131 B안)가 있으면 목표 세우기를 부른다. 요청도 후보도 없으면 모델을
  부르지 않는다(목표 0개 → 지휘 루프도 모델 없이 한 번 최적화). 목표 세우기가 실패하면 요청 전체가 "반영하지 못했어요"로 남고 코스는
  기본 목표로 짠다.
- 영업시간은 `OpeningHoursGateway`로 읽는다. 시작 스냅샷도 같은 게이트웨이에서 만든다(`start_hours`).
- 실행 상한(#1609): 서비스는 run의 created_at을 기준 시각으로 넘긴다. 목표 세우기와 지휘 턴 앞에서 `direct.past_limit`을 보고, 지났으면
  모델을 더 부르지 않고 코드 규칙이 마무리한다. 작업 기록에 그 단계를 남기고 결과(outcome)에 timed_out을 반영한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

from dataclasses import replace

from agent.course import core, direct, goals as goals_mod, review as review_mod, worklog
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
    review: Optional[review_mod.ReviewResult] = None     # 다 넣은 일정(review 모드)의 점검과 고칠 안. 응답에는 아직 내지 않는다(다음 PR)


def start_hours(trip: core.Trip, gateway: OpeningHoursGateway) -> dict[str, dict[int, core.DayStatus]]:
    """시작 스냅샷이 아는 영업시간 — 장소 별칭 → 요일 → 상태. 모르는 장소는 칸이 없다(모름)."""
    found = gateway.get_opening_hours([p.place_id for p in trip.places])
    return {p.alias: dict(found[p.place_id]) for p in trip.places if found.get(p.place_id)}


def _usage_meta(*metered: Any) -> tuple[Optional[str], Optional[str]]:
    usages = [u for m in metered if m is not None for u in m.usages]
    models = list(dict.fromkeys(u.model for u in usages if u.model))
    versions = list(dict.fromkeys(u.prompt_version for u in usages if u.prompt_version))
    return (", ".join(models) or None), (", ".join(versions) or None)


def _whole(text: str) -> tuple[str, ...]:
    """목표를 세우지 못했을 때 요청 전체를 unmatched로. 맡기는 말뿐이면(「알아서 잘 짜줘」) 빈 요청과 같다(#1128)."""
    return () if goals_mod.is_delegation(text) else (text,)


def run_course(
    build: TripBuild, request_text: str, *,
    goals_planner: Optional[Callable[[Mapping[str, Any]], Any]],
    direct_planner: Optional[Callable[[Mapping[str, Any]], Any]],
    gateway: OpeningHoursGateway, on_step: Optional[OnStepRecord] = None,
    map_items: Sequence[goals_mod.SummaryItem] = (),
    started_at: Optional[datetime] = None, clock: direct.Clock = direct.utc_now,
) -> Computation:
    """build.trip이 있어야 한다(too_few면 호출하지 않는다). 모델 호출 실패는 던지지 않는다 — 기준선이 대신한다.

    on_step(record)는 작업 기록 단계(`worklog.StepRecord`)가 생길 때마다 순서대로 부른다: 목표 세우기 뒤의 "이해", 확인 문장, 지휘 턴마다의
    생각·도구 결과·검증 줄·기본값 답, 마지막 "결과". 콜백이 던져도 계산은 계속한다(진행 표시는 부가 기능이다).

    started_at은 실행 상한의 기준 시각(run의 created_at)이고 clock은 지금 시각이다(테스트가 주입한다). 없으면 상한이 없다."""
    trip = build.trip
    assert trip is not None
    text = request_text.strip()[:REQUEST_TEXT_MAX_CHARS]
    candidates = goals_mod.map_candidates(trip, map_items)
    setter = GoalSetter(goals_planner) if goals_planner is not None and (text or candidates) else None
    decider = DirectDecider(direct_planner) if direct_planner is not None else None
    goals: tuple[goals_mod.Goal, ...] = ()
    unmatched: tuple[str, ...] = ()
    understood_by = worklog.MODEL
    goals_failure: Optional[str] = None
    goals_timed_out = False
    if text or (setter is not None and candidates):
        if setter is None:                       # 목표를 세울 모델 자리가 없다 — 요청 전체를 반영하지 못했다고 밝힌다
            unmatched, understood_by = _whole(text), "코드(목표 세우기 없음)"
        elif direct.past_limit(started_at, clock):     # 실행 상한이 이미 지났다(큐 대기 등) — 부르지 않고 기본 목표로 짠다(#1609)
            unmatched, understood_by = (_whole(text) if text else ()), "코드(실행 상한)"
            goals_failure, goals_timed_out = direct.DEADLINE, True
        else:
            try:
                verified = goals_mod.verify_goal_set(trip, text, setter(goals_mod.goals_input(trip, text, candidates)), candidates)
                goals, unmatched = verified.goals, verified.unmatched
            except ModelTurnFailed as exc:       # 결과는 끝까지 낸다 — 이어받았다는 줄은 Narrator가 남긴다(#1131 D안)
                unmatched, understood_by = (_whole(text) if text else ()), "코드(목표 세우기 실패)"
                goals_failure = direct.failure_kind(exc)

    def emit(recs: list[worklog.StepRecord]) -> None:
        for rec in recs:
            if on_step is None:
                continue
            try:
                on_step(rec)
            except Exception as exc:   # noqa: BLE001 — 진행 저장 실패가 코스 계산을 멈추면 안 된다. 클래스 이름만 로그
                log.warning("course 진행 기록 실패: %s", type(exc).__name__)

    narrator = worklog.Narrator(trip, goals, unmatched, understood_by=understood_by, candidates=candidates, goals_failure=goals_failure)
    records = narrator.opening()
    emit(records)

    def on_direct_step(step: direct.DirectStep, ds: direct.DirectState) -> None:
        new = narrator.step(step, goals=ds.state.goals)
        records.extend(new)
        emit(new)

    state = initial_state(trip, start_hours(trip, gateway), build.schedule, goals, build.locks)
    mode = build.mode or "plan"
    judge = None
    if mode == "review":       # 다 넣은 일정은 코드가 점검과 안을 먼저 만들고, 그 결과를 지휘 턴 입력에 실어 모델이 선호 문제를 판단하게 한다(#1321 PR C)
        assert build.schedule is not None
        judge = review_mod.judge_input(review_mod.review(trip, build.schedule, state.hours, state.goals))
    result = direct.run_direct(state, decide=decider, hours=gateway, unmatched_count=len(unmatched),
                              on_step=on_direct_step, review_input=judge.payload if judge else None,
                              started_at=started_at, clock=clock)
    if goals_timed_out and not result.timed_out:     # 목표 세우기에서 상한이 지났다 — 지휘는 목표가 없어 모델을 부르지 않았어도 상한으로 끝난 run이다
        result = replace(result, timed_out=True, outcome=core.outcome(
            result.violations, timed_out=True, checks=len(core.find_checks(trip, result.course, result.state.hours))))
    reviewed = None
    unassigned: tuple[str, ...] = ()
    if mode == "review":       # 다 넣은 일정 — 사람이 정한 그대로(그날 순서까지) 점검한다. 일정과 locks는 바꾸지 않고 안은 제안일 뿐이다
        assert build.schedule is not None
        hours = result.state.hours
        violations = core.find_violations(trip, build.schedule, hours)
        result = replace(
            result, course=build.schedule, violations=violations,
            goal_results=goals_mod.evaluate_all(trip, build.schedule, result.state.goals),
            outcome=core.outcome(violations, timed_out=result.timed_out, checks=len(core.find_checks(trip, build.schedule, hours))),
        )
        order, worth = review_mod.hooks_of(judge, result.judgment) if judge and result.judgment else (None, None)    # 판단이 없으면 코드 기본(입력 순서, 모두 고침)
        reviewed = review_mod.review(trip, build.schedule, hours, result.state.goals, order=order, worth=worth)
    elif mode == "fill":       # 남은 곳을 채운 안을 점검한다. AI가 둔 미배정 장소는 자기 카드가 있어 ②③으로 따로 옮기지 않는다
        unassigned = tuple(p.alias for p in trip.places if p.alias not in build.locks)
        reviewed = review_mod.review(trip, result.course, result.state.hours, result.state.goals, movable=set(build.locks))
    if reviewed is not None:
        known = {g.id: g for g in (*state.goals, *result.state.goals)}       # 판단 줄은 점검 때의 문제를 말한다 — 그 뒤에 바뀐 목표도 이름을 붙일 수 있게
        found = worklog.review_records(trip, tuple(known.values()), reviewed, judge=judge, decision=result.judgment, asked=result.asked_model)
        records.extend(found)
        emit(found)
    closing = narrator.closing(result, reviewed=reviewed)
    records.extend(closing)
    emit(closing)
    model, prompt_version = _usage_meta(setter, decider)
    tokens = [m.tokens for m in (setter, decider) if m is not None]
    return Computation(
        view=build_view(trip, build.excluded, goals, unmatched, result, records, mode=mode, reviewed=reviewed, unassigned=unassigned),
        model_turns=result.model_turns,
        tokens_in=sum(t[0] for t in tokens), tokens_out=sum(t[1] for t in tokens),
        model=model, prompt_version=prompt_version, review=reviewed,
    )

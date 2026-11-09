"""지휘 루프(pivot 3절) — 모델은 optimize·lock·finish를 부리고, 코스 계산은 코드(optimize.py)가 한다.

기존 한 수씩 루프(loop.py)와 프롬프트(course-turn)는 그대로 남아 있다(비교용 driver). 이 루프는 최대 DIRECT_MAX_TURNS턴이다.
- 목표가 0개면 모델을 부르지 않고 optimize 1회로 끝낸다(0원).
- 모델 호출이 실패하거나 쓸 수 없는 호출(상한 초과)이면 그 턴은 코드 규칙이 대신한다: 후보가 없으면 optimize, 있으면 가장 나은 후보로 finish.
- 요청자에게 되묻지 않는다(#1131). 쉬는 날에 걸린 목표와 이동이 넘치는 날은 턴 앞에서 코드가 찾기 → 옮겨 보기 → 비교 → 결정으로 푼다
  (resolve_closure, resolve_split — 모델 호출을 쓰지 않는다). 영업시간을 모르는 곳은 여는 것으로 보고, 작업 기록에 가정 줄로 남긴다.
- 실행 상한(#1609): 기준 시각(run의 created_at)을 받으면 모델을 부르기 전마다 남은 시간을 본다. 넘었으면 더 부르지 않고 그 턴부터
  코드 규칙이 마무리한다(모델 실패 때와 같은 길, 이미 시작한 호출은 끊지 않는다). 기준 시각이 없으면(평가·시연) 상한이 없다.
DB·시간 말고는 순수하다. 모델 자리는 `decide`로, 시계는 `clock`으로 주입한다(deps.DirectDecider).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from pydantic import ValidationError

from agent.course import baseline, core, goals as goals_mod, optimize as opt, verify
from agent.course.constants import DIRECT_MAX_TURNS, MODEL_FAILURES, RUN_LIMIT
from agent.course.optimize import Candidate
from agent.course.ports import OpeningHoursGateway
from agent.course.schemas import MoveDay, ReorderDay
from agent.course.state import State
from agent.course.tools import ToolResult, _fail
from llm.api import CourseReviewDecision, verify_course_review
from llm.schemas import CourseDirectFinish, CourseDirectTurn, CourseLockCall, CourseOptimize, CourseReviewCall

Decide = Callable[[dict[str, Any]], CourseDirectTurn]
OnStep = Callable[["DirectStep", "DirectState"], None]
Clock = Callable[[], datetime]
UNUSABLE_ERRORS = ("LIMIT_EXCEEDED",)       # 이 오류가 나면 그 턴은 코드 규칙이 대신한다. 그 밖의 오류는 메시지가 계획에 도움이 된다
MODEL_FAILED = "MODEL_FAILED"               # 모델 턴이 실패해 코드가 이어받았다(substituted_for.error, #1131 D안)
RUN_DEADLINE = "RUN_DEADLINE"               # 실행 상한이 지나 모델을 부르지 않고 코드가 이어받았다(substituted_for.error, #1609)
# 이어받은 원인의 종류 — 작업 기록 문구를 고르는 데만 쓴다. 예외 메시지와 모델 원문은 남기지 않는다
TIMEOUT, BAD_FORMAT, NO_RESPONSE, UNUSABLE = "timeout", "format", "no_response", "unusable"
DEADLINE = "deadline"                       # 실행 상한(모델 실패가 아니라 부르지 않은 것, #1609)
_FAILURE_OF_REASON = {"timeout": TIMEOUT, "invalid_schema": BAD_FORMAT, "call_failed": NO_RESPONSE}   # llm AgentCallFailed.reason


def failure_kind(exc: BaseException) -> str:
    """모델 실패 예외 → 원인 종류. deps.ModelTurnFailed는 llm이 정한 reason을 들고 온다(.failure.reason)."""
    reason = getattr(getattr(exc, "failure", None), "reason", None)
    if reason in _FAILURE_OF_REASON:
        return _FAILURE_OF_REASON[reason]
    if isinstance(exc, TimeoutError):
        return TIMEOUT
    return BAD_FORMAT if isinstance(exc, ValidationError) else NO_RESPONSE
RESOLVE_CLOSURE, RESOLVE_SPLIT = "resolve_closure", "resolve_split"     # 코드가 푸는 단계의 도구 이름(작업 기록이 이 이름으로 줄을 만든다)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def past_limit(started_at: Optional[datetime], clock: Clock) -> bool:
    """기준 시각(run의 created_at)부터 실행 상한(constants.RUN_LIMIT)이 지났다 — 모델을 더 부르지 않는다. 상한 판정은 여기 한 곳이다
    (목표 세우기 앞은 runner, 지휘 턴 앞은 run_direct가 부른다). 기준 시각이 없으면(평가·시연) 상한이 없다."""
    return started_at is not None and clock() - started_at >= RUN_LIMIT


@dataclass(frozen=True)
class DirectStep:
    turn: int
    by: str                                # model | baseline(코드 규칙 대행) | code(코드가 연 단계)
    thought: Optional[str]
    thought_problem: Optional[str]
    call: dict[str, Any]
    result: ToolResult
    substituted_for: Optional[dict[str, Any]] = None
    guard: tuple[str, ...] = ()            # 모델 문장이 코드 사실과 어긋나 코드 문장으로 바꿨다면 그 이유들(화면용 한국어)
    blocked_thought: Optional[str] = None  # 바꾸기 전 모델 원문(별칭 슬롯 그대로). 화면에는 내지 않는다 — 시도 기록용
    note: Optional[str] = None             # 코드가 푼 단계의 결정 문장(검증을 거쳐 이름을 넣은 것). 모델 입력에는 넣지 않는다


@dataclass(frozen=True)
class DirectState:
    state: State
    candidates: tuple[Candidate, ...] = ()
    optimize_calls: int = 0
    checks: tuple[dict, ...] = ()          # check_goals 결과(코드가 첫 단계에서 부른다)
    resolved: frozenset[str] = frozenset()  # 코드가 이미 푼 것(목표 id, "split:d2") — 같은 것을 두 번 풀지 않는다
    review_input: Optional[Mapping[str, Any]] = None        # 다 넣은 일정의 점검 입력(review.judge_input().payload, 별칭만). 없으면 review 도구를 쓸 수 없다
    judgment: Optional[CourseReviewDecision] = None         # 모델이 낸 점검 판단 중 입력과 맞는 것(llm이 검증). 한 번만 받는다


@dataclass(frozen=True)
class DirectResult:
    outcome: str
    chosen: Candidate
    course: core.Course
    violations: tuple[core.Violation, ...]
    soft: dict[str, Any]
    goal_results: tuple[goals_mod.GoalResult, ...]
    steps: tuple[DirectStep, ...]
    candidates: tuple[Candidate, ...]
    state: State
    model_turns: int
    checks: tuple[dict, ...] = ()
    judgment: Optional[CourseReviewDecision] = None
    timed_out: bool = False                # 실행 상한이 지나 모델을 더 부르지 않고 코드가 마무리했다(#1609)

    @property
    def asked_model(self) -> bool:
        """모델 턴을 한 번이라도 불렀다(실패해 코드가 이어받은 턴 포함)."""
        return any(s.by == "model" or s.substituted_for for s in self.steps)

    @property
    def guarded(self) -> int:
        """검증이 모델 문장을 코드 문장으로 바꾼 수."""
        return sum(bool(s.guard) for s in self.steps)


# ---- 입력과 요약 ----

def _walk(trip: core.Trip, course: core.Course) -> dict[str, int]:
    """도보 분(하루 최대·합계)과 대중교통 구간 수·하루 이동 최대(도보+대중교통)."""
    walks = [core.day_walk(trip, d) for d in course]
    travels = [core.day_travel(trip, d) for d in course]
    return {"day_max": max(walks, default=0), "total": sum(walks), "transit_legs": core.course_transit_legs(trip, course),
            "travel_day_max": max(travels, default=0)}


def candidate_summary(state: State, c: Candidate) -> dict[str, Any]:
    trip = state.trip
    return {
        "candidate_id": c.candidate_id,
        "priority": list(c.priority),
        "hard": core.hard_summary(trip, state.hours, c.course, c.violations),
        "focus": c.focus,
        "balanced": c.balanced,
        "goals": [{"id": r.goal.id, "met": r.met, "value": r.value} for r in goals_mod.evaluate_all(trip, c.course, state.goals)],
        "kept": [r.goal.id for r in goals_mod.evaluate_all(trip, c.course, state.goals) if r.met is True],
        "gave_up": [r.goal.id for r in goals_mod.evaluate_all(trip, c.course, state.goals) if r.met is not True],
        "walk": _walk(trip, c.course),
        "soft": core.soft_scores(trip, c.course),
    }


def direct_input(ds: DirectState, last: Optional[ToolResult], turn: int, unmatched_count: int) -> dict[str, Any]:
    """지휘 턴 입력. 별칭과 점수만 넣는다 — 장소 이름, 좌표, id는 넣지 않는다."""
    state = ds.state
    return {
        "turn": turn,
        "goals": [{"id": g.id, "kind": g.kind, "day": g.day, "places": list(g.places), "source": g.origin,
                   **({"tag": g.tag} if g.tag else {})} for g in state.goals],
        "unmatched_count": unmatched_count,
        "goal_checks": list(ds.checks),
        "optimize_calls": ds.optimize_calls,
        "candidates": [candidate_summary(state, c) for c in ds.candidates],
        "locks": [{"place": p, "day": d} for p, d in sorted(state.locks.items())],
        "checks": [{"place": v.places[0], "day": v.day} for v in core.find_checks(state.trip, state.course, state.hours)],
        "last_result": last.as_input() if last else None,
        **({"review": ds.review_input} if ds.review_input is not None and ds.judgment is None else {}),     # 판단을 받은 뒤에는 다시 묻지 않는다
        "budget": {"turns_left": DIRECT_MAX_TURNS - turn + 1},
    }


# ---- 도구 실행 ----

def best_candidate(state: State, candidates: tuple[Candidate, ...]) -> Candidate:
    """코드 규칙으로 가장 나은 후보: 강한 기준선의 사전식 비교(확정 위반 → 확인 필요 → 요청 목표 → 기본 목표). 동점이면 먼저 만든 후보."""
    return min(candidates, key=lambda c: baseline.strong_key(state, c.course, c.violations))


def pending_closure(ds: DirectState) -> Optional[dict]:
    """check_goals가 "쉬는 날에 걸렸다"고 한 목표 중 아직 안 풀었고 옮길 여는 날이 있는 첫 번째.
    옮길 날이 하나도 없으면 풀지 않는다(목표를 코드가 대신 빼지 않는다) — 이유는 확인 줄에 남는다."""
    by_id = {g.id: g for g in ds.state.goals}
    for check in ds.checks:
        goal = by_id.get(check["id"])
        if goal is None or goal.id in ds.resolved or not set(check["reasons"]) & set(goals_mod.CLOSURE_CODES):
            continue
        days = goals_mod.alternative_days(ds.state.trip, ds.state.hours, goal)
        if days:
            return {"goal": goal, "check": check, "days": days}
    return None


SPLIT_OPTIONS_MAX = 3


@dataclass(frozen=True)
class SplitOption:
    """코드가 계산한 나누기 하나: 이 날의 places를 to_day로 옮기고 닿은 두 날의 순서를 다시 짠 코스(확정 위반이 지금보다 줄어드는 것만)."""
    option_id: str                       # m1, m2 …
    places: tuple[str, ...]
    to_day: str
    course: core.Course
    violations: tuple[core.Violation, ...]


def _travel_blockers(violations) -> list[core.Violation]:
    """남은 확정 위반 중 이동(도보 구간·하루 도보·하루 이동 합계)과 구성원 도보 조건 — 날을 나눠야 풀리는 것."""
    return [v for v in violations if v.status == "confirmed" and v.kind in ("travel", "member")]


def _walk_clusters(trip: core.Trip, day: tuple[str, ...]) -> list[tuple[str, ...]]:
    """그 날 장소를 걸어서 이어지는 묶음(지역)으로 — 단일 연결, 걷는 구간(직선거리 WALK_MAX_M 이하)만 이은다. 하루 안의 순서를 유지한다."""
    left, out = list(day), []
    while left:
        comp, stack = [left.pop(0)], []
        stack.append(comp[0])
        while stack:
            x = stack.pop()
            near = [y for y in left if core.leg_between(trip, x, y).mode == "walk"]
            for y in near:
                left.remove(y)
                comp.append(y)
                stack.append(y)
        out.append(tuple(sorted(comp, key=day.index)))
    return out


def split_options(state: State, course: core.Course, day: str) -> tuple[SplitOption, ...]:
    """day(날짜 별칭)의 이동 위반을 줄이는 나누기를 코드가 모두 따져 좋은 순으로 SPLIT_OPTIONS_MAX개까지.
    후보는 그 날의 지역 묶음 또는 장소 하나를 다른 날로 옮기는 것이다. 옮긴 뒤 닿은 두 날의 순서를 다시 짜고, 전체 확정 위반이 지금보다
    엄격히 줄어들 때만 선택지가 된다(고정과 어긋나는 것은 뺀다). 순위는 (확정 위반, 대중교통 구간 수, 이동 합계, 옮기는 장소 수)."""
    trip = state.trip
    i = core.day_index(trip, day)
    assert i is not None
    current = core.hard_score(core.find_violations(trip, course, state.hours))[0]
    units = list(dict.fromkeys([*_walk_clusters(trip, course[i]), *[(p,) for p in course[i]]]))
    found: dict[core.Course, tuple[tuple, tuple[str, ...], str, tuple[core.Violation, ...]]] = {}
    for unit in units:
        for j in range(len(trip.days)):
            if j == i:
                continue
            try:
                moved = course
                for p in unit:
                    moved = core.apply_move(trip, moved, MoveDay(type="move_day", place=p, to_day=core.day_alias(j), position=None), state.locks)
                for k in (i, j):
                    order = core.best_day_order(trip, moved[k])
                    if order != tuple(moved[k]):
                        moved = core.apply_move(trip, moved, ReorderDay(type="reorder_day", day=core.day_alias(k), places=list(order)), state.locks)
            except core.MoveError:
                continue
            violations = core.find_violations(trip, moved, state.hours)
            if core.hard_score(violations)[0] >= current:
                continue
            key = (core.hard_score(violations), core.course_transit_legs(trip, moved), core.course_travel(trip, moved), len(unit), j)
            if moved not in found or key < found[moved][0]:
                found[moved] = (key, unit, core.day_alias(j), violations)
    ranked = sorted(found.items(), key=lambda kv: kv[1][0])[:SPLIT_OPTIONS_MAX]
    return tuple(SplitOption(f"m{n + 1}", unit, to_day, c, v) for n, (c, (_, unit, to_day, v)) in enumerate(ranked))


def pending_split(ds: DirectState) -> Optional[dict]:
    """지금 가장 나은 후보에 확정 이동 위반이 남았고, 코드가 위반을 줄이는 나누기를 찾았으면 그 날과 선택지. 날마다 한 번만 푼다.
    줄이는 나누기가 하나도 없으면 풀지 않는다(없는 선택지를 지어내지 않는다)."""
    if not ds.candidates:
        return None
    best = best_candidate(ds.state, ds.candidates)
    blockers = _travel_blockers(best.violations)
    if not blockers:
        return None
    for day in dict.fromkeys(v.day for v in blockers):
        if f"split:{day}" in ds.resolved:
            continue
        options = split_options(ds.state, best.course, day)
        if options:
            return {"day": day, "options": options, "course": best.course, "violation": next(v for v in blockers if v.day == day)}
    return None


def _check_result(ds: DirectState) -> ToolResult:
    by_id = {g.id: g for g in ds.state.goals}
    return ToolResult("check_goals", ok=True, data={
        "checks": list(ds.checks),
        "sentences": [goals_mod.check_sentence(ds.state.trip, c, by_id[c["id"]]) for c in ds.checks],
    })


# ---- 코드가 푸는 단계 (#1131) — 찾기 → 옮겨 보기 → 비교 → 결정. 요청자에게 묻지 않는다 ----

@dataclass(frozen=True)
class Resolved:
    ds: DirectState
    result: ToolResult
    note: str                              # 결정 문장(검증을 거쳐 이름을 넣은 것)
    guard: tuple[str, ...] = ()            # 코드 문장이 사실과 어긋나 바꿨다면 그 이유(있으면 안 되는 일 — 화면에 검증 줄로 남는다)


def _tried(state: State, cands: tuple[Candidate, ...]) -> tuple[Candidate, dict[str, Any]]:
    best = best_candidate(state, cands)
    results = goals_mod.evaluate_all(state.trip, best.course, state.goals)
    return best, {"confirmed": core.hard_score(best.violations)[0], "kept": sum(r.met is True for r in results), "total": len(results)}


def _decided(state: State, best: Candidate, cands: tuple[Candidate, ...], slot_text: str) -> tuple[str, tuple[str, ...]]:
    """결정 문장(슬롯 원문)을 모델 문장과 같은 검증에 건다. 어긋나면 코드 사실 문장으로 바꾼다."""
    ref = verify.Reference(state.trip, state.hours, best.course, best.violations, state.goals, "후보", len(cands))
    guarded = verify.guard(ref, slot_text)
    return (guarded.replacement, guarded.reasons) if guarded else (core.render_thought(state.trip, slot_text), ())


def resolve_closure(ds: DirectState, pend: dict, gateway: OpeningHoursGateway) -> Resolved:
    """쉬는 날에 걸린 목표: 여는 날을 찾고(alternative_days), 날마다 목표를 그 날로 옮겨 optimize로 짜 본 뒤, 강한 기준선 순서(확정 위반 →
    확인 필요 → 요청 목표)로 견줘 가장 나은 날로 목표를 고친다. 장소를 빼거나 목표를 지우지 않는다. 동점이면 앞 날짜."""
    state, goal = ds.state, pend["goal"]
    trials = []
    for day in pend["days"]:
        new_goal = goals_mod.retarget(goal, day)
        goals = tuple(dict.fromkeys(new_goal if g.id == goal.id else g for g in state.goals))
        priority = tuple(new_goal.id if i == goal.id else i for i in state.priority)
        tried_state, cands = opt.optimize(replace(state, goals=goals, priority=priority), priority=priority, gateway=gateway)
        best, summary = _tried(tried_state, cands)
        trials.append((day, new_goal, tried_state, cands, best, summary))
    day, new_goal, new_state, cands, best, _ = min(trials, key=lambda t: baseline.strong_key(t[2], t[4].course, t[4].violations))
    if goal.kind == "place_on_day":
        closed = [goal.places[0]]
        slot = f"{{{goal.places[0]}}}는 {{{goal.day}}}에 쉬어요. 그래서 이 목표를 {{{day}}}로 옮겨 정했어요."
    else:
        facts = pend["check"]["facts"].get("night_closed_days", {})
        closed = [p for p, days in facts.items() if goal.day in days]
        slot = f"{{{goal.day}}}엔 야경 장소가 모두 쉬어요. 그래서 야경 목표를 {{{day}}}로 옮겨 정했어요."
    note, guard = _decided(new_state, best, cands, slot)
    ds = replace(ds, state=new_state, checks=goals_mod.check_goals(new_state.trip, new_state.hours, new_state.goals), candidates=cands,
                 optimize_calls=ds.optimize_calls + len(trials), resolved=ds.resolved | {goal.id, new_goal.id})
    return Resolved(ds, ToolResult(RESOLVE_CLOSURE, ok=True, data={
        "goal_before": goal.id, "goal_after": new_goal.id, "closed_day": goal.day, "closed_places": closed,
        "tried": [{"day": d, **s} for d, _, _, _, _, s in trials], "chosen_day": day,
    }), note, guard)


def resolve_split(ds: DirectState, split: dict, gateway: OpeningHoursGateway) -> Resolved:
    """이동이 넘치는 날: 코드가 찾은 나누기마다 옮긴 장소를 그 날에 고정하고 optimize로 짜 본 뒤, 강한 기준선 순서로 견줘 가장 나은 나누기를
    고른다. 동점이면 split_options 순서(확정 위반이 적고 대중교통·이동이 짧은 것)."""
    state, day = ds.state, split["day"]
    trials = []
    for o in split["options"]:
        locks = {**state.locks, **{p: o.to_day for p in o.places}}
        tried_state, cands = opt.optimize(opt.with_course(replace(state, locks=locks), o.course), priority=state.priority, gateway=gateway)
        best, summary = _tried(tried_state, cands)
        trials.append((o, tried_state, cands, best, summary))
    o, new_state, cands, best, _ = min(trials, key=lambda t: baseline.strong_key(t[1], t[3].course, t[3].violations))
    moved = "와 ".join(f"{{{p}}}" for p in o.places)
    note, guard = _decided(new_state, best, cands, f"{{{day}}} 이동이 길어서 {moved}를 {{{o.to_day}}}로 옮겨 나눴어요.")
    ds = replace(ds, state=new_state, candidates=cands, optimize_calls=ds.optimize_calls + len(trials), resolved=ds.resolved | {f"split:{day}"})
    return Resolved(ds, ToolResult(RESOLVE_SPLIT, ok=True, data={
        "day": day, "violation": split["violation"].id,
        "tried": [{"option_id": t[0].option_id, "places": list(t[0].places), "to_day": t[0].to_day, **t[4]} for t in trials],
        "chosen": o.option_id, "moved": list(o.places), "to_day": o.to_day,
    }), note, guard)


def resolve_next(ds: DirectState, gateway: OpeningHoursGateway) -> Optional[Resolved]:
    """지금 코드가 풀 것이 있으면 하나 푼다. 쉬는 날에 걸린 목표가 먼저, 그다음 이동이 넘치는 날."""
    if (pend := pending_closure(ds)) is not None:
        return resolve_closure(ds, pend, gateway)
    if (split := pending_split(ds)) is not None:
        return resolve_split(ds, split, gateway)
    return None

def _comparison(state: State, candidates: tuple[Candidate, ...], chosen_id: str) -> dict[str, Any]:
    """끝낼 때 견준 후보들(#1131 C안). 목표가 없으면 비교하지 않는다(모델 0회 경로). 별칭과 숫자만 — 작업 기록이 문장으로 만든다.
    코스가 같은 후보는 한 행만 남긴다(고른 후보와 같으면 고른 후보를, 아니면 먼저 만든 후보를) — 없는 차이를 쓰지 않는다.
    distinct는 코스가 서로 다른 후보 수(남은 행 수와 같다), code_best는 코드 규칙으로 가장 나은 후보."""
    if not state.goals:
        return {}
    chosen = next(c for c in candidates if c.candidate_id == chosen_id)
    kept: dict[core.Course, Candidate] = {chosen.course: chosen}
    for c in candidates:
        kept.setdefault(c.course, c)
    rows = []
    for c in sorted(kept.values(), key=lambda c: candidates.index(c)):
        results = goals_mod.evaluate_all(state.trip, c.course, state.goals)
        walk = _walk(state.trip, c.course)
        rows.append({"candidate_id": c.candidate_id, "kept": [r.goal.id for r in results if r.met is True],
                     "total": len(results), "confirmed": core.hard_score(c.violations)[0], "walk_day_max": walk["day_max"],
                     "transit_legs": walk["transit_legs"], "focus": c.focus, "balanced": c.balanced})
    return {"compare": rows, "distinct": len({c.course for c in candidates}),
            "code_best": kept[best_candidate(state, candidates).course].candidate_id}      # 남긴 행의 id로(같은 코스면 같은 안이다)


def execute(call, ds: DirectState, gateway: OpeningHoursGateway, by: str = "model") -> tuple[DirectState, ToolResult]:
    state, tool = ds.state, call.tool
    if isinstance(call, CourseOptimize):
        ids = {g.id for g in state.goals}
        bad = [p for p in call.priority if p not in ids]
        if bad:
            return ds, _fail(tool, "INVALID_ID", f"모르는 목표 id {bad[0]}")
        locks: dict[str, str] = {}
        for spec in call.locks:
            if not state.trip.has_place(spec.place) or core.day_index(state.trip, spec.day) is None:
                return ds, _fail(tool, "INVALID_ID", f"{spec.place}/{spec.day}는 없는 장소나 날짜다")
            if state.locks.get(spec.place, spec.day) != spec.day:
                return ds, _fail(tool, "LOCKED", f"{spec.place}는 {state.locks[spec.place]}에 고정돼 있다")
            locks[spec.place] = spec.day
        by_id = {g.id: g for g in state.goals}
        priority = sorted(call.priority, key=lambda i: by_id[i].origin == "map")     # 요청 목표가 지도 목표보다 앞이다(#1131 B안)
        new_state, candidates = opt.optimize(state, priority=priority, locks=locks, gateway=gateway)
        ds = replace(ds, state=new_state, candidates=candidates, optimize_calls=ds.optimize_calls + 1)
        return ds, ToolResult(tool, ok=True, data={"candidates": [candidate_summary(new_state, c) for c in candidates]})

    if isinstance(call, CourseLockCall):
        if not state.trip.has_place(call.place) or core.day_index(state.trip, call.day) is None:
            return ds, _fail(tool, "INVALID_ID", f"{call.place}/{call.day}는 없는 장소나 날짜다")
        if state.locks.get(call.place, call.day) != call.day:
            return ds, _fail(tool, "LOCKED", f"{call.place}는 {state.locks[call.place]}에 고정돼 있다 — 고정은 풀 수 없다")
        new_state = opt.apply_locks(state, {call.place: call.day})
        # 고정이 바뀌었으니 이전 후보는 낡았다 — optimize를 다시 불러야 한다
        return replace(ds, state=new_state, candidates=()), ToolResult(
            tool, ok=True, data={"locks": [{"place": p, "day": d} for p, d in sorted(new_state.locks.items())]})

    if isinstance(call, CourseDirectFinish):
        chosen = next((c for c in ds.candidates if c.candidate_id == call.candidate_id), None)
        if chosen is None:
            return ds, _fail(tool, "INVALID_ID", f"{call.candidate_id}는 지금 있는 후보가 아니다 — optimize를 먼저 부른다")
        least = min(core.hard_score(c.violations)[0] for c in ds.candidates)
        if core.hard_score(chosen.violations)[0] > least:
            return ds, _fail(tool, "WORSENS_HARD", "확정 위반이 더 적은 후보가 있다 — 그 후보를 고른다")
        return ds, ToolResult(tool, ok=True, data={"candidate_id": chosen.candidate_id, **_comparison(state, ds.candidates, chosen.candidate_id)})
    if isinstance(call, CourseReviewCall):
        # 점검 판단(#1326, #1321 PR C). 입력에 review가 있는 턴(다 넣은 일정)에서만 받는다. 입력과 맞는지는 llm이 검증하고(재요청 없음),
        # 버려진 자리는 코드 기본(입력 순서, 모두 고침)이 잇는다 — 그래서 모델이 무엇을 내도 하드 문제의 카드는 그대로 나온다.
        if ds.review_input is None:
            return ds, _fail(tool, "NOT_REVIEW_MODE", "지금 run에서는 점검 도구를 쓸 수 없다 — optimize나 finish를 부른다")
        if ds.judgment is not None:
            return ds, _fail(tool, "ALREADY_REVIEWED", "점검 판단은 이미 받았다 — optimize나 finish를 부른다")
        decision = verify_course_review(ds.review_input, call)
        return replace(ds, judgment=decision), ToolResult(tool, ok=True, data={
            "order": list(decision.order),
            "worth": {a: list(v) for a, v in decision.worth.items()},
            "picks": {a: list(v) for a, v in decision.picks.items()},
        })
    raise TypeError(f"실행할 수 없는 도구 {type(call).__name__}")


# ---- 루프 ----

def _fallback_call(ds: DirectState):
    state = ds.state
    if not ds.candidates:
        return CourseOptimize(tool="optimize", priority=[g.id for g in state.goals], locks=[])
    return CourseDirectFinish(tool="finish", candidate_id=best_candidate(state, ds.candidates).candidate_id)


def _reference(before: DirectState, after: DirectState, call, result: ToolResult) -> verify.Reference:
    """모델 문장을 견줄 코드 사실. finish면 고른 후보, 아니면 모델이 그때 본 후보 중 코드 규칙으로 가장 나은 후보(없으면 초안).
    영업시간은 그 턴 뒤의 것을 쓴다(optimize가 새로 알아낸 휴무까지)."""
    state = before.state
    chosen = None
    if isinstance(call, CourseDirectFinish) and result.ok:
        chosen = next((c for c in before.candidates if c.candidate_id == result.data["candidate_id"]), None)
    if chosen is None and before.candidates:
        chosen = best_candidate(state, before.candidates)
    course, violations = (chosen.course, chosen.violations) if chosen else (state.course, state.violations)
    return verify.Reference(
        state.trip, after.state.hours, course, violations, state.goals,
        "후보" if chosen else "초안", len(before.candidates),
    )


def run_direct(
    state: State, *, decide: Optional[Decide], hours: OpeningHoursGateway, unmatched_count: int = 0,
    on_step: Optional[OnStep] = None, review_input: Optional[Mapping[str, Any]] = None,
    started_at: Optional[datetime] = None, clock: Clock = utc_now,
) -> DirectResult:
    """on_step(step, ds)는 단계가 하나 생길 때마다(순서대로, 그 단계가 반영된 상태와 함께) 부른다 — 진행 중 저장용.
    started_at은 실행 상한의 기준 시각(run의 created_at)이다. 모델을 부르기 전마다 `past_limit`을 보고, 지났으면 그 턴부터 코드 규칙이
    마무리하며 결과의 timed_out을 채운다.
    review_input은 다 넣은 일정(review 모드)의 점검 입력이다. 있으면 모델 입력에 `review`로 실리고 모델은 review 도구로 판단을 낸다(모델 턴 수 그대로)."""
    ds = DirectState(state, review_input=review_input)
    steps: list[DirectStep] = []

    def emit(step: DirectStep) -> None:
        steps.append(step)
        if on_step is not None:
            on_step(step, ds)

    def resolve_all(turn: int, last: Optional[ToolResult]) -> Optional[ToolResult]:
        """코드가 풀 것을 다 푼다(모델 턴을 쓰지 않는다). 쉬는 날을 풀어 목표가 바뀌면 다시 확인하고 그 결과를 모델에 준다."""
        nonlocal ds
        while (done := resolve_next(ds, hours)) is not None:
            ds = done.ds
            emit(DirectStep(turn, "code", None, None, {"tool": done.result.tool}, done.result, guard=done.guard, note=done.note))
            last = done.result
            if done.result.tool == RESOLVE_CLOSURE:
                last = _check_result(ds)
                emit(DirectStep(turn, "code", None, None, {"tool": "check_goals"}, last))
        return last

    last: Optional[ToolResult] = None
    if state.goals:                                              # 첫 단계: 코드가 데이터 확인을 자동으로 부르고 결과를 모델 입력에 넣는다
        checks = goals_mod.check_goals(state.trip, state.hours, state.goals)
        ds = replace(ds, checks=checks)
        last = _check_result(ds)
        emit(DirectStep(0, "code", None, None, {"tool": "check_goals"}, last))
    use_model = decide is not None and bool(state.goals)       # 목표가 없으면 모델을 부르지 않는다
    finished = timed_out = False

    for turn in range(1, DIRECT_MAX_TURNS + 1):
        last = resolve_all(turn, last)
        if not use_model and ds.candidates:                     # 모델 없이: 짜고 풀었으면 가장 나은 후보로 끝낸다
            call = _fallback_call(ds)
            ds, result = execute(call, ds, hours)
            emit(DirectStep(turn, "baseline", None, None, call.model_dump(), result))
            finished = True
            break
        thought = problem = substituted = raw_thought = None
        call, by = None, "baseline"
        if use_model and past_limit(started_at, clock):         # 실행 상한 — 더 부르지 않고 이 턴부터 코드 규칙이 마무리한다(#1609)
            use_model, timed_out = False, True
            substituted = {"call": None, "error": RUN_DEADLINE, "failure": DEADLINE}
        if use_model:
            try:
                reply = decide(direct_input(ds, last, turn, unmatched_count))
                call, by = reply.action, "model"
                problem = core.thought_problem(ds.state.trip, reply.thought)
                thought = None if problem else core.render_thought(ds.state.trip, reply.thought)
                raw_thought = None if problem else reply.thought
            except MODEL_FAILURES as exc:                     # 이어받은 것을 작업 기록에 남긴다(#1131 D안)
                call = None
                substituted = {"call": None, "error": MODEL_FAILED, "failure": failure_kind(exc)}
        if call is None:
            call = _fallback_call(ds)
        before = ds
        new_ds, result = execute(call, ds, hours, by)
        if by == "model" and not result.ok and result.error in UNUSABLE_ERRORS:
            substituted = {"call": call.model_dump(), "error": result.error, "failure": UNUSABLE}
            call, by, thought, problem = _fallback_call(ds), "baseline", None, None
            new_ds, result = execute(call, ds, hours, by)
        ds = new_ds
        guard_reasons, blocked = (), None
        if thought and by == "model":                            # 화면에 나갈 모델 문장이 코드 사실과 어긋나면 코드 문장으로 바꾼다(다시 부르지 않는다)
            guarded = verify.guard(_reference(before, ds, call, result), raw_thought)
            if guarded:
                guard_reasons, blocked, thought = guarded.reasons, raw_thought, guarded.replacement
        emit(DirectStep(turn, by, thought, problem, call.model_dump(), result, substituted, guard_reasons, blocked))
        last = result
        if isinstance(call, CourseDirectFinish) and result.ok:
            finished = True
            break

    if not finished:                                            # 턴이 다 됐다 — 남은 것을 풀고 코드 규칙으로 골라 끝낸다(끝 단계를 기록에 남긴다)
        resolve_all(len(steps), last)
        if not ds.candidates:
            ds, result = execute(_fallback_call(ds), ds, hours)
            emit(DirectStep(len(steps) + 1, "baseline", None, None,
                            CourseOptimize(tool="optimize", priority=[], locks=[]).model_dump(), result))
        call = _fallback_call(ds)
        ds, result = execute(call, ds, hours)
        emit(DirectStep(len(steps) + 1, "baseline", None, None, call.model_dump(), result))
    chosen_id = steps[-1].result.data["candidate_id"]
    chosen = next(c for c in ds.candidates if c.candidate_id == chosen_id)
    trip = ds.state.trip
    return DirectResult(
        outcome=core.outcome(chosen.violations, timed_out=timed_out, checks=len(core.find_checks(trip, chosen.course, ds.state.hours))),
        chosen=chosen, course=chosen.course, violations=chosen.violations, soft=core.soft_scores(trip, chosen.course),
        goal_results=goals_mod.evaluate_all(trip, chosen.course, ds.state.goals), steps=tuple(steps),
        candidates=ds.candidates, state=ds.state,
        model_turns=sum(s.by == "model" for s in steps), checks=ds.checks, judgment=ds.judgment, timed_out=timed_out,
    )

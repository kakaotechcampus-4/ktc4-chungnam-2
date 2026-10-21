"""지휘 루프(pivot 3절) — 모델은 optimize·lock·ask_requester·finish를 부리고, 코스 계산은 코드(optimize.py)가 한다.

기존 한 수씩 루프(loop.py)와 프롬프트(course-turn)는 그대로 남아 있다(비교용 driver). 이 루프는 최대 DIRECT_MAX_TURNS턴이다.
- 목표가 0개면 모델을 부르지 않고 optimize 1회로 끝낸다(0원).
- 모델 호출이 실패하거나 쓸 수 없는 호출(상한 초과)이면 그 턴은 코드 규칙이 대신한다: 후보가 없으면 optimize, 있으면 가장 나은 후보로 finish.
- ask_requester는 이번에는 질문 카드를 만들어 기록하고 기본 선택지로 이어 간다(답을 받아 이어 가는 것은 앱 연결 때).
DB·시간 말고는 순수하다. 모델 자리는 `decide`로 주입한다(deps.DirectDecider).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Optional

from pydantic import ValidationError

from agent.course import baseline, core, goals as goals_mod, optimize as opt, verify
from agent.course.constants import ASK_MAX, DIRECT_MAX_TURNS
from agent.course.korean import attach
from agent.course.optimize import Candidate
from agent.course.ports import OpeningHoursGateway
from agent.course.state import State
from agent.course.tools import ToolResult, _fail
from llm.schemas import CourseAskRequester, CourseDirectFinish, CourseDirectTurn, CourseLockCall, CourseOptimize

Decide = Callable[[dict[str, Any]], CourseDirectTurn]
OnStep = Callable[["DirectStep", "DirectState"], None]
MODEL_FAILURES = (ValidationError, RuntimeError, TimeoutError)
UNUSABLE_ERRORS = ("LIMIT_EXCEEDED",)       # 이 오류가 나면 그 턴은 코드 규칙이 대신한다. 그 밖의 오류는 메시지가 계획에 도움이 된다
CLOSED_DAY_DEFAULT = "모르겠어요"


@dataclass(frozen=True)
class Question:
    """요청자에게 갈 질문 카드(문구는 코드 템플릿). 이번에는 답을 받지 않고 default로 이어 간다."""
    question_id: str
    kind: str
    subject: Optional[str]
    options: tuple[str, ...]
    text: str
    default: str
    option_labels: tuple[str, ...] = ()
    default_reason: str = ""


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


@dataclass(frozen=True)
class DirectState:
    state: State
    candidates: tuple[Candidate, ...] = ()
    questions: tuple[Question, ...] = ()
    preferred: Optional[str] = None        # pick_course의 기본 선택지 — 답이 없으니 이 후보로 이어 간다
    optimize_calls: int = 0
    checks: tuple[dict, ...] = ()          # check_goals 결과(코드가 첫 단계에서 부른다)


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
    questions: tuple[Question, ...]
    state: State
    model_turns: int
    checks: tuple[dict, ...] = ()

    @property
    def guarded(self) -> int:
        """검증이 모델 문장을 코드 문장으로 바꾼 수."""
        return sum(bool(s.guard) for s in self.steps)


# ---- 입력과 요약 ----

def _walk(trip: core.Trip, course: core.Course) -> dict[str, int]:
    days = [core.day_travel(trip, d) for d in course]
    return {"day_max": max(days, default=0), "total": sum(days)}


def candidate_summary(state: State, c: Candidate) -> dict[str, Any]:
    trip = state.trip
    return {
        "candidate_id": c.candidate_id,
        "priority": list(c.priority),
        "hard": core.hard_summary(trip, state.hours, c.course, c.violations),
        "focus": c.focus,
        "goals": [{"id": r.goal.id, "met": r.met, "value": r.value} for r in goals_mod.evaluate_all(trip, c.course, state.goals)],
        "kept": [r.goal.id for r in goals_mod.evaluate_all(trip, c.course, state.goals) if r.met is True],
        "gave_up": [r.goal.id for r in goals_mod.evaluate_all(trip, c.course, state.goals) if r.met is not True],
        "walk": _walk(trip, c.course),
        "soft": core.soft_scores(trip, c.course),
    }


def _must_ask(ds: DirectState) -> Optional[dict]:
    if (pend := pending_closure(ds)) is not None:
        return {"kind": "choose_day", "subject": pend["goal"].id, "closed_day": pend["goal"].day, "options": pend["days"]}
    if (pair := ask_trigger(ds)) is not None:
        return {"kind": "pick_course", "candidates": list(pair)}
    return None


def direct_input(ds: DirectState, last: Optional[ToolResult], turn: int, unmatched_count: int) -> dict[str, Any]:
    """지휘 턴 입력. 별칭과 점수만 넣는다 — 장소 이름, 좌표, id는 넣지 않는다."""
    state = ds.state
    return {
        "turn": turn,
        "goals": [{"id": g.id, "kind": g.kind, "day": g.day, "places": list(g.places),
                   **({"tag": g.tag} if g.tag else {})} for g in state.goals],
        "unmatched_count": unmatched_count,
        "goal_checks": list(ds.checks),
        "optimize_calls": ds.optimize_calls,
        "must_ask": _must_ask(ds),
        "candidates": [candidate_summary(state, c) for c in ds.candidates],
        "locks": [{"place": p, "day": d} for p, d in sorted(state.locks.items())],
        "asked": len(ds.questions),
        "checks": [{"place": v.places[0], "day": v.day} for v in core.find_checks(state.trip, state.course, state.hours)],
        "last_result": last.as_input() if last else None,
        "budget": {"turns_left": DIRECT_MAX_TURNS - turn + 1, "asks_left": ASK_MAX - len(ds.questions)},
    }


# ---- 도구 실행 ----

def best_candidate(state: State, candidates: tuple[Candidate, ...], preferred: Optional[str] = None) -> Candidate:
    """코드 규칙으로 가장 나은 후보: 강한 기준선의 사전식 비교(확정 위반 → 확인 필요 → 요청 목표 → 기본 목표). 동점이면 먼저 만든 후보."""
    key = lambda c: (baseline.strong_key(state, c.course, c.violations), c.candidate_id != preferred)
    return min(candidates, key=key)


DROP = "drop"       # choose_day의 마지막 선택지: 그 목표는 빼기(기본값이 아니다 — 기본값은 늘 코드가 고른 여는 날이다)


def pending_closure(ds: DirectState) -> Optional[dict]:
    """check_goals가 "쉬는 날에 걸렸다"고 한 목표 중 아직 안 물었고 옮길 여는 날이 있는 첫 번째. 질문 상한 안에서만 있다.
    옮길 날이 하나도 없으면 묻지 않는다(목표를 코드가 대신 빼지 않는다) — 이유는 확인 줄에 남는다."""
    if len(ds.questions) >= ASK_MAX:
        return None
    asked = {q.subject for q in ds.questions if q.kind == "choose_day"}
    by_id = {g.id: g for g in ds.state.goals}
    for check in ds.checks:
        goal = by_id.get(check["id"])
        if goal is None or goal.id in asked or not set(check["reasons"]) & set(goals_mod.CLOSURE_CODES):
            continue
        days = goals_mod.alternative_days(ds.state.trip, ds.state.hours, goal)
        if days:
            return {"goal": goal, "check": check, "days": days}
    return None


def _closure_call(pend: dict) -> CourseAskRequester:
    return CourseAskRequester(tool="ask_requester", kind="choose_day", subject=pend["goal"].id, options=list(pend["days"]))


def _check_result(ds: DirectState) -> ToolResult:
    by_id = {g.id: g for g in ds.state.goals}
    return ToolResult("check_goals", ok=True, data={
        "checks": list(ds.checks),
        "sentences": [goals_mod.check_sentence(ds.state.trip, c, by_id[c["id"]]) for c in ds.checks],
    })


def _choose_day(ds: DirectState, pend: dict, options: list[str], proposed_by: str) -> tuple[DirectState, ToolResult]:
    """쉬는 날에 걸린 목표를 물어보고, 답이 없으니 첫 선택지(기본값)로 목표를 고쳐 이어 간다. 장소를 빼지 않는다."""
    state, goal, trip = ds.state, pend["goal"], ds.state.trip
    default = options[0]
    labels = tuple([core.day_label(trip, d) for d in options] + ["그 목표는 빼기"])
    if goal.kind == "place_on_day":
        name = trip.place(goal.places[0]).name
        text = f"{attach(name, '은/는')} {core.day_label(trip, goal.day)}에 쉬어요. {attach(core.day_label(trip, default), '으로/로')} 옮길까요?"
        answer = f"{attach(name, '을/를')} {core.day_label(trip, default)}에 두는 걸로 이어 가요"
    else:
        closed = [trip.place(p).name for p in pend["check"]["facts"]["night_closed_days"] if goal.day in pend["check"]["facts"]["night_closed_days"][p]]
        text = f"{core.day_label(trip, goal.day)}엔 야경 장소 {attach(', '.join(closed), '이/가')} 쉬어요. 야경은 {core.day_label(trip, default)} 마지막으로 할까요?"
        answer = f"야경 목표를 {core.day_label(trip, default)}로 바꿔 이어 가요"
    reason = "쉬는 날엔 둘 수 없어서 여는 날을 기본값으로 했어요, " + ("모델이 제안한 날" if proposed_by == "model" else "코드가 고른 첫 여는 날")
    question = Question(f"q{len(ds.questions) + 1}", "choose_day", goal.id, tuple([*options, DROP]), text, default, labels, reason)
    new_goal = goals_mod.retarget(goal, default)
    goals = tuple(dict.fromkeys(new_goal if g.id == goal.id else g for g in state.goals))
    priority = tuple(new_goal.id if i == goal.id else i for i in state.priority)
    new_state = replace(state, goals=goals, priority=priority)
    checks = goals_mod.check_goals(trip, new_state.hours, goals)
    ds = replace(ds, state=new_state, checks=checks, questions=(*ds.questions, question), candidates=(), preferred=None)
    return ds, ToolResult("ask_requester", ok=True, data={
        "question_id": question.question_id, "default": default, "note": "답을 받지 않고 기본 선택지로 이어 간다",
        "answer": answer, "goal_before": goal.id, "goal_after": new_goal.id,
    })


def ask_trigger(ds: DirectState) -> Optional[tuple[str, str]]:
    """질문을 여는 조건(코드): optimize 2회 이상 + 요청 목표 미달 + 목표별 met가 서로 다른 후보 2개 이상. 맞으면 보여줄 두 후보 id.
    첫 후보는 코드 규칙으로 가장 나은 후보(기본 선택지)이고, 둘째는 met 벡터가 그와 다른 첫 후보다. pick_course는 run당 한 번이다."""
    if ds.optimize_calls < 2 or len(ds.candidates) < 2 or len(ds.questions) >= ASK_MAX:
        return None
    if any(q.kind == "pick_course" for q in ds.questions):
        return None
    state = ds.state
    best = best_candidate(state, ds.candidates)
    if all(r.met is True for r in goals_mod.evaluate_all(state.trip, best.course, state.goals)):
        return None
    vector = opt.met_vector(state, best.course)
    other = next((c for c in ds.candidates if c is not best and opt.met_vector(state, c.course) != vector), None)
    return (best.candidate_id, other.candidate_id) if other else None


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
        new_state, candidates = opt.optimize(state, priority=call.priority, locks=locks, gateway=gateway)
        ds = replace(ds, state=new_state, candidates=candidates, preferred=None, optimize_calls=ds.optimize_calls + 1)
        return ds, ToolResult(tool, ok=True, data={"candidates": [candidate_summary(new_state, c) for c in candidates]})

    if isinstance(call, CourseLockCall):
        if not state.trip.has_place(call.place) or core.day_index(state.trip, call.day) is None:
            return ds, _fail(tool, "INVALID_ID", f"{call.place}/{call.day}는 없는 장소나 날짜다")
        if state.locks.get(call.place, call.day) != call.day:
            return ds, _fail(tool, "LOCKED", f"{call.place}는 {state.locks[call.place]}에 고정돼 있다 — 고정은 풀 수 없다")
        new_state = opt.apply_locks(state, {call.place: call.day})
        # 고정이 바뀌었으니 이전 후보는 낡았다 — optimize를 다시 불러야 한다
        return replace(ds, state=new_state, candidates=(), preferred=None), ToolResult(
            tool, ok=True, data={"locks": [{"place": p, "day": d} for p, d in sorted(new_state.locks.items())]})

    if isinstance(call, CourseAskRequester):
        return _ask(call, ds, by)

    if isinstance(call, CourseDirectFinish):
        chosen = next((c for c in ds.candidates if c.candidate_id == call.candidate_id), None)
        if chosen is None:
            return ds, _fail(tool, "INVALID_ID", f"{call.candidate_id}는 지금 있는 후보가 아니다 — optimize를 먼저 부른다")
        least = min(core.hard_score(c.violations)[0] for c in ds.candidates)
        if core.hard_score(chosen.violations)[0] > least:
            return ds, _fail(tool, "WORSENS_HARD", "확정 위반이 더 적은 후보가 있다 — 그 후보를 고른다")
        if ds.preferred is not None and chosen.candidate_id != ds.preferred:
            # 질문에 답이 없어 기본 선택지로 이어 간다 — 모델이 다른 후보로 끝내려 해도 기본 선택지가 이긴다(요청자가 안 정한 것을 모델이 정하지 않는다)
            return ds, ToolResult(tool, ok=True, data={"candidate_id": ds.preferred, "note": "질문에 답이 없어 기본 선택지로 끝냈다"})
        return ds, ToolResult(tool, ok=True, data={"candidate_id": chosen.candidate_id})
    raise TypeError(f"실행할 수 없는 도구 {type(call).__name__}")


def _ask(call: CourseAskRequester, ds: DirectState, by: str = "model") -> tuple[DirectState, ToolResult]:
    state, tool = ds.state, call.tool
    if len(ds.questions) >= ASK_MAX:
        return ds, _fail(tool, "LIMIT_EXCEEDED", f"질문은 이번 코스에서 {ASK_MAX}번까지다")
    qid = f"q{len(ds.questions) + 1}"
    if call.kind == "choose_day":
        pend = pending_closure(ds)
        if pend is None or call.subject != pend["goal"].id:
            return ds, _fail(tool, "INVALID_ID", "choose_day는 쉬는 날에 걸린 목표(must_ask.subject)를 subject로 줘야 한다")
        if not call.options or len(set(call.options)) != len(call.options) or any(o not in pend["days"] for o in call.options):
            return ds, _fail(tool, "INVALID_MOVE", "options는 그 목표를 옮길 수 있는 여는 날(must_ask.options)만, 첫 번째가 제안하는 날이어야 한다")
        return _choose_day(ds, pend, list(call.options), by)
    if call.kind == "pick_course":
        ids = [c.candidate_id for c in ds.candidates]
        if len(call.options) < 2 or any(o not in ids for o in call.options) or len(set(call.options)) != len(call.options):
            return ds, _fail(tool, "INVALID_MOVE", "pick_course는 지금 있는 후보 둘 이상을 options에 줘야 한다")
        lines = []
        for letter, cid in zip("AB", call.options):
            cand = next(c for c in ds.candidates if c.candidate_id == cid)
            parts = [goals_mod.short_label(state.trip, r.goal, r.met is True)
                     for r in goals_mod.evaluate_all(state.trip, cand.course, state.goals) if r.goal.kind != "daily_walk_low"]
            parts.append(f"하루 최대 {_walk(state.trip, cand.course)['day_max']}분")
            lines.append(f"{letter}: " + "·".join(parts))
        question = Question(qid, call.kind, None, tuple(call.options), " / ".join(lines) + ". 어느 쪽?", call.options[0])
        ds = replace(ds, questions=(*ds.questions, question), preferred=question.default)
    else:
        checks = {v.places[0] for v in core.find_checks(state.trip, state.course, state.hours)}
        if call.subject is None or call.subject not in checks:
            return ds, _fail(tool, "INVALID_ID", "ask_closed_day는 영업 여부를 모르는 장소(checks)를 subject로 줘야 한다")
        name = state.trip.place(call.subject).name
        question = Question(qid, call.kind, call.subject, ("열어요", "쉬어요", CLOSED_DAY_DEFAULT),
                            f"{attach(name, '이/가')} 여행 기간에 여는지 아시나요?", CLOSED_DAY_DEFAULT)
        ds = replace(ds, questions=(*ds.questions, question))
    return ds, ToolResult(tool, ok=True, data={
        "question_id": question.question_id, "default": question.default, "note": "답을 받지 않고 기본 선택지로 이어 간다",
    })


# ---- 루프 ----

def _ask_call(pair: tuple[str, str]) -> CourseAskRequester:
    return CourseAskRequester(tool="ask_requester", kind="pick_course", subject=None, options=list(pair))


def _fallback_call(ds: DirectState):
    state = ds.state
    if not ds.candidates:
        return CourseOptimize(tool="optimize", priority=[g.id for g in state.goals], locks=[])
    return CourseDirectFinish(tool="finish", candidate_id=best_candidate(state, ds.candidates, ds.preferred).candidate_id)


def _reference(before: DirectState, after: DirectState, call, result: ToolResult) -> verify.Reference:
    """모델 문장을 견줄 코드 사실. finish면 고른 후보, 아니면 모델이 그때 본 후보 중 코드 규칙으로 가장 나은 후보(없으면 초안).
    영업시간은 그 턴 뒤의 것을 쓴다(optimize가 새로 알아낸 휴무까지)."""
    state = before.state
    chosen = None
    if isinstance(call, CourseDirectFinish) and result.ok:
        chosen = next((c for c in before.candidates if c.candidate_id == result.data["candidate_id"]), None)
    if chosen is None and before.candidates:
        chosen = best_candidate(state, before.candidates, before.preferred)
    course, violations = (chosen.course, chosen.violations) if chosen else (state.course, state.violations)
    return verify.Reference(
        state.trip, after.state.hours, course, violations, state.goals,
        "후보" if chosen else "초안", len(before.candidates),
    )


def run_direct(
    state: State, *, decide: Optional[Decide], hours: OpeningHoursGateway, unmatched_count: int = 0,
    on_step: Optional[OnStep] = None,
) -> DirectResult:
    """on_step(step, ds)는 단계가 하나 생길 때마다(순서대로, 그 단계가 반영된 상태와 함께) 부른다 — 진행 중 저장용."""
    ds = DirectState(state)
    steps: list[DirectStep] = []

    def emit(step: DirectStep) -> None:
        steps.append(step)
        if on_step is not None:
            on_step(step, ds)

    last: Optional[ToolResult] = None
    if state.goals:                                              # 첫 단계: 코드가 데이터 확인을 자동으로 부르고 결과를 모델 입력에 넣는다
        checks = goals_mod.check_goals(state.trip, state.hours, state.goals)
        ds = replace(ds, checks=checks)
        last = _check_result(ds)
        emit(DirectStep(0, "code", None, None, {"tool": "check_goals"}, last))
    use_model = decide is not None and bool(state.goals)       # 목표가 없으면 모델을 부르지 않는다
    finished = False

    for turn in range(1, DIRECT_MAX_TURNS + 1):
        thought = problem = substituted = raw_thought = None
        call, by = None, "baseline"
        if use_model:
            try:
                reply = decide(direct_input(ds, last, turn, unmatched_count))
                call, by = reply.action, "model"
                problem = core.thought_problem(ds.state.trip, reply.thought)
                thought = None if problem else core.render_thought(ds.state.trip, reply.thought)
                raw_thought = None if problem else reply.thought
            except MODEL_FAILURES:
                call = None
        if call is None:
            call = _fallback_call(ds)
        pend = pending_closure(ds)
        if pend and not (isinstance(call, CourseAskRequester) and call.kind == "choose_day"):
            # 쉬는 날에 걸린 목표는 짜기 전에 먼저 묻는다 — 모델이 다른 행동을 골라도 코드가 질문을 연다(여는 날 중 첫날이 기본값)
            substituted = {"call": call.model_dump(), "error": "QUESTION_OPENED_BY_CODE"}
            call, by, thought, problem = _closure_call(pend), "code", None, None
        pair = ask_trigger(ds) if isinstance(call, CourseDirectFinish) else None
        if pair:                                                 # 끝내려는데 물을 조건이 되어 있다 — 코드가 질문을 대신 연다
            substituted = {"call": call.model_dump(), "error": "QUESTION_OPENED_BY_CODE"}
            call, by, thought, problem = _ask_call(pair), "code", None, None
        before = ds
        new_ds, result = execute(call, ds, hours, by)
        if pend and by == "model" and not result.ok:             # 모델이 낸 choose_day 질문이 틀렸다 — 코드가 대신 연다
            substituted = {"call": call.model_dump(), "error": result.error}
            call, by, thought, problem = _closure_call(pend), "code", None, None
            new_ds, result = execute(call, ds, hours, by)
        elif by == "model" and not result.ok and result.error in UNUSABLE_ERRORS:
            substituted = {"call": call.model_dump(), "error": result.error}
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
        if isinstance(call, CourseAskRequester) and call.kind == "choose_day" and result.ok:
            last = _check_result(ds)                             # 답으로 목표가 바뀌었다 — 코드가 다시 확인하고 그 결과를 모델에 준다
            emit(DirectStep(turn, "code", None, None, {"tool": "check_goals"}, last))
        if isinstance(call, CourseDirectFinish) and result.ok:
            finished = True
            break
        if not use_model and ds.candidates:                     # 모델 없이 optimize 한 번이면 끝이다
            call = _fallback_call(ds)
            ds, result = execute(call, ds, hours)
            emit(DirectStep(turn, "baseline", None, None, call.model_dump(), result))
            finished = True
            break

    if not finished:                                            # 턴이 다 됐다 — 코드 규칙으로 고른다
        pair = ask_trigger(ds)
        if pair:
            ds, result = execute(_ask_call(pair), ds, hours, "code")
            emit(DirectStep(len(steps), "code", None, None, _ask_call(pair).model_dump(), result,
                                    {"call": {"tool": "finish"}, "error": "QUESTION_OPENED_BY_CODE"}))
        if not ds.candidates:
            ds, result = execute(_fallback_call(ds), ds, hours)
            emit(DirectStep(len(steps) + 1, "baseline", None, None,
                                    CourseOptimize(tool="optimize", priority=[], locks=[]).model_dump(), result))
    if finished:
        chosen_id = steps[-1].result.data["candidate_id"]
        chosen = next(c for c in ds.candidates if c.candidate_id == chosen_id)
    else:
        chosen = best_candidate(ds.state, ds.candidates, ds.preferred)
    trip = ds.state.trip
    return DirectResult(
        outcome=core.outcome(chosen.violations, timed_out=False, checks=len(core.find_checks(trip, chosen.course, ds.state.hours))),
        chosen=chosen, course=chosen.course, violations=chosen.violations, soft=core.soft_scores(trip, chosen.course),
        goal_results=goals_mod.evaluate_all(trip, chosen.course, ds.state.goals), steps=tuple(steps),
        candidates=ds.candidates, questions=ds.questions, state=ds.state,
        model_turns=sum(s.by == "model" for s in steps), checks=ds.checks,
    )

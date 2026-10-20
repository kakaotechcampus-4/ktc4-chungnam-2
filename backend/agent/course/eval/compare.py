"""평가 지도에서 세 가지를 비교한다: 초안만 / 코드 기준선 / 강한 기준선(기본 목표까지) / 에이전트(실모델, 선택).

    cd backend && .venv/bin/python -m agent.course.eval.compare [--data agent/course/eval/data] [--model --max-maps 5] [--unknown-as-violation]

세 코스 모두 **진짜 영업시간(지도의 hours 전체)** 으로 채점한다 — 에이전트가 조회로 알아낸 것만 아는 상태에서 짠 코스가
실제로는 어떤지 본다. 실모델은 `--model`을 주고 지도를 5개 이하로 제한했을 때만 돈다(비용, 사용자 확인 뒤에 쓴다).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent.course import baseline, core, direct, goals as goals_mod, loop, worklog
from agent.course.constants import REQUEST_TEXT_MAX_CHARS
from agent.course.deps import ModelTurnFailed
from agent.course.core import Course, MemberConstraint, Place, Trip
from agent.course.ports import FixtureOpeningHours
from agent.course.state import initial_state

MODEL_MAP_CAP = 5     # 실모델 상한(사용자 지시: 한 번에 지도 5개 이내)


@dataclass(frozen=True)
class Scenario:
    trip: Trip
    truth: dict[str, dict[int, core.DayStatus]]       # 장소 별칭 → 진짜 영업시간
    start_hours: dict[str, dict[int, core.DayStatus]]  # 시작 스냅샷이 아는 것
    gateway: FixtureOpeningHours                       # 조회 도구가 돌려주는 진짜 값(place_id = source_id)


def scenario_from_map(m: Mapping[str, Any], unknown_hours: str = "check") -> Scenario:
    places = tuple(
        Place(p["alias"], f"pin-{p['alias']}", p["source_id"], p["name"], p["category"], p["lat"], p["lng"], frozenset(p["labels"]))
        for p in m["places"]
    )
    trip = Trip(
        places=places,
        days=tuple(date.fromisoformat(d) for d in m["days"]),
        member_constraints=tuple(MemberConstraint(**c) for c in m["member_constraints"]),
        unknown_hours=unknown_hours,   # type: ignore[arg-type]
    )
    truth = {p["alias"]: {int(wd): s for wd, s in p["hours"].items()} for p in m["places"]}
    start = {p["alias"]: truth[p["alias"]] for p in m["places"] if p["known_at_start"]}
    gateway = FixtureOpeningHours({p["source_id"]: truth[p["alias"]] for p in m["places"]})
    return Scenario(trip, truth, start, gateway)


@dataclass(frozen=True)
class Score:
    hard_confirmed: int
    hard_unknown: int
    soft: dict[str, Optional[float]]
    turns: int = 0          # 도구를 쓴 턴 수(초안만은 0)


def score(sc: Scenario, course: Course, turns: int = 0) -> Score:
    violations = core.find_violations(sc.trip, course, sc.truth)
    confirmed = core.hard_score(violations)[0]
    unknown = len(core.find_checks(sc.trip, course, sc.truth))      # 진짜 영업시간으로도 모르는 곳(모드와 무관)
    return Score(confirmed, unknown, core.soft_scores(sc.trip, course), turns)


def run_variants(sc: Scenario, decide: Optional[Callable] = None) -> dict[str, Score]:
    draft = core.draft_course(sc.trip)
    out = {"draft": score(sc, draft)}
    base = loop.run_loop(initial_state(sc.trip, sc.start_hours, draft), decide=None, hours=sc.gateway)
    out["baseline"] = score(sc, base.best_course, len(base.steps))
    strong = loop.run_loop(initial_state(sc.trip, sc.start_hours, draft), decide=None, hours=sc.gateway,
                           policy=baseline.next_action_strong)
    out["strong"] = score(sc, strong.best_course, len(strong.steps))
    if decide is not None:
        agent = loop.run_loop(initial_state(sc.trip, sc.start_hours, draft), decide=decide, hours=sc.gateway)
        out["agent"] = score(sc, agent.best_course, len(agent.steps))
    return out


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def aggregate(results: Sequence[Mapping[str, Score]]) -> dict[str, dict[str, Optional[float]]]:
    """변형별 평균. hard_solved = 확정 위반 0인 지도 비율."""
    table: dict[str, dict[str, Optional[float]]] = {}
    for variant in results[0]:
        rows = [r[variant] for r in results]
        table[variant] = {
            "hard_solved": sum(s.hard_confirmed == 0 for s in rows) / len(rows),
            "hard_confirmed": _mean([s.hard_confirmed for s in rows]),
            "hard_unknown": _mean([s.hard_unknown for s in rows]),
            "cafe_after_meal": _mean([s.soft["cafe_after_meal"] for s in rows]),
            "night_last": _mean([s.soft["night_last"] for s in rows]),
            "mono_category_days": _mean([s.soft["mono_category_days"] for s in rows]),
            "no_tour_days": _mean([s.soft["no_tour_days"] for s in rows]),
            "day_balance": _mean([s.soft["day_balance"] for s in rows]),
            "meal_per_day": _mean([s.soft["meal_per_day"] for s in rows]),
            "cafe_spacing": _mean([s.soft["cafe_spacing"] for s in rows]),
            "travel_total": _mean([s.soft["travel_total"] for s in rows]),
            "turns": _mean([s.turns for s in rows]),
        }
    return table


def format_table(table: Mapping[str, Mapping[str, Optional[float]]], n_maps: int) -> str:
    cols = list(next(iter(table.values())))
    fmt = lambda v: "-" if v is None else f"{v:.2f}"
    lines = [f"지도 {n_maps}개 평균 (진짜 영업시간으로 채점)", "변형      " + "  ".join(f"{c:>15}" for c in cols)]
    lines += [f"{name:<9} " + "  ".join(f"{fmt(row[c]):>15}" for c in cols) for name, row in table.items()]
    return "\n".join(lines)


def load_maps(data_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((data_dir / "maps").glob("map_*.json"))]


# ---- 요청 목표 비교 (pivot 4절) ----

@dataclass(frozen=True)
class RequestScore:
    score: Score
    gold_met: int                       # 정답 목표 중 최종 코스가 지킨 수(판단할 수 없는 목표는 뺀다)
    gold_total: int                     # 정답 목표 수(판단 불가 목표도 분모에 들어가고 못 이룬 것으로 센다)
    gold_undecidable: int = 0           # 그중 라벨을 몰라 판단할 수 없었던 수(따로 보고)
    goals_exact: Optional[bool] = None  # 에이전트만: 만든 목표가 정답과 종류·매개변수까지 일치
    goals_trap_ok: Optional[bool] = None  # 에이전트만: 정답이 목표 0개인 지도에서 0개를 냈다
    calls: int = 0
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: int = 0
    worklog: tuple[str, ...] = ()       # 작업 기록(8.3 표 모양). 에이전트·정답 주입에만 있다


def _goal_sig(g: goals_mod.Goal) -> tuple:
    return (g.kind, g.day, tuple(sorted(g.places)))


def gold_goals(sc: Scenario, req: Mapping[str, Any]) -> tuple[goals_mod.Goal, ...]:
    out = []
    for g in req["gold_goals"]:
        goal, why = goals_mod.normalize(sc.trip, g["kind"], g["day"], g["places"])
        if goal is None:
            raise ValueError(f"정답 목표가 지도와 안 맞는다: {why}")
        out.append(goal)
    return tuple(out)


def request_score(sc: Scenario, course: Course, gold: Sequence[goals_mod.Goal], **extra: Any) -> RequestScore:
    met, total = goals_mod.met_count(sc.trip, course, gold)
    return RequestScore(score(sc, course), met, total, goals_mod.undecidable_count(sc.trip, course, gold), **extra)


def run_request_variants(
    sc: Scenario, req: Mapping[str, Any], *, goal_setter: Optional[Callable] = None, decider: Optional[Callable] = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, RequestScore]:
    """초안 / 강한 기준선(요청을 모름) / 강한 기준선 + 정답 목표 / 에이전트(목표 세우기 + 지휘, 모델 자리가 있을 때)."""
    gold = gold_goals(sc, req)
    draft = core.draft_course(sc.trip)
    out = {"draft": request_score(sc, draft, gold)}

    def climb_with(goals: tuple[goals_mod.Goal, ...], decide=None, unmatched=0):
        return direct.run_direct(initial_state(sc.trip, sc.start_hours, draft, goals), decide=decide, hours=sc.gateway,
                                 unmatched_count=unmatched)

    out["strong"] = request_score(sc, climb_with(()).course, gold)
    gold_run = climb_with(gold)
    out["strong_gold"] = request_score(sc, gold_run.course, gold, worklog=tuple(worklog.render(
        sc.trip, gold, req["gold_unmatched"], gold_run, understood_by="정답 주입")))
    if goal_setter is not None and decider is not None:
        started = clock()
        text = req["request_text"][:REQUEST_TEXT_MAX_CHARS]
        verified = goals_mod.VerifiedGoals((), (text,), ())
        try:
            verified = goals_mod.verify_goal_set(sc.trip, text, goal_setter(goals_mod.goals_input(sc.trip, text)))
        except ModelTurnFailed:
            pass                                          # 목표 세우기 실패 → 요청 목표 없이 진행(기본 목표만)
        result = climb_with(verified.goals, decider, len(verified.unmatched))
        out["agent"] = request_score(
            sc, result.course, gold,
            goals_exact={_goal_sig(g) for g in verified.goals} == {_goal_sig(g) for g in gold},
            goals_trap_ok=(not verified.goals) if not gold else None,
            worklog=tuple(worklog.render(sc.trip, verified.goals, verified.unmatched, result)),
            calls=goal_setter.calls + decider.calls, seconds=clock() - started,
            tokens_in=goal_setter.tokens[0] + decider.tokens[0], tokens_out=goal_setter.tokens[1] + decider.tokens[1],
            failures=len(goal_setter.failures) + len(decider.failures),
        )
    return out


def aggregate_requests(results: Sequence[Mapping[str, RequestScore]]) -> dict[str, dict[str, Optional[float]]]:
    table: dict[str, dict[str, Optional[float]]] = {}
    for variant in results[0]:
        rows = [r[variant] for r in results]
        judged = [r for r in rows if r.gold_total]      # 정답 목표가 있는 지도만(함정 지도는 분모가 0)
        exact = [r.goals_exact for r in rows if r.goals_exact is not None]
        trap = [r.goals_trap_ok for r in rows if r.goals_trap_ok is not None]
        table[variant] = {
            "goal_met": _mean([r.gold_met / r.gold_total for r in judged]),
            "undecidable": sum(r.gold_undecidable for r in rows),
            "hard_solved": sum(r.score.hard_confirmed == 0 for r in rows) / len(rows),
            "hard_confirmed": _mean([r.score.hard_confirmed for r in rows]),
            "cafe_after_meal": _mean([r.score.soft["cafe_after_meal"] for r in rows]),
            "night_last": _mean([r.score.soft["night_last"] for r in rows]),
            "meal_per_day": _mean([r.score.soft["meal_per_day"] for r in rows]),
            "day_balance": _mean([r.score.soft["day_balance"] for r in rows]),
            "travel_total": _mean([r.score.soft["travel_total"] for r in rows]),
            "goals_exact": (sum(exact) / len(exact)) if exact else None,
            "trap_zero": (sum(trap) / len(trap)) if trap else None,
            "model_calls": _mean([r.calls for r in rows]),
            "seconds": _mean([r.seconds for r in rows]),
            "tokens_in": _mean([r.tokens_in for r in rows]),
            "tokens_out": _mean([r.tokens_out for r in rows]),
            "failures": sum(r.failures for r in rows),
        }
    return table


def _main_requests(args: argparse.Namespace) -> None:
    maps = load_maps(args.data)
    requests = {r["map_id"]: r for r in json.loads(args.requests.read_text(encoding="utf-8"))}
    if args.only:
        wanted = args.only.split(",")
        maps = [m for m in maps if m["id"] in wanted]
    goal_setter = decider = None
    if args.model:
        limit = min(args.max_maps or MODEL_MAP_CAP, MODEL_MAP_CAP)
        maps = maps[:limit]
        from agent.course.deps import DirectDecider, GoalSetter     # 실모델 설정(.env)이 필요할 때만 가져온다
        from llm.api import real_course_direct_planner, real_course_goals_planner
    elif args.max_maps:
        maps = maps[: args.max_maps]
    results = []
    for m in maps:
        if args.model:
            goal_setter, decider = GoalSetter(real_course_goals_planner), DirectDecider(real_course_direct_planner)
        results.append(run_request_variants(scenario_from_map(m), requests[m["id"]], goal_setter=goal_setter, decider=decider))
    print(format_table(aggregate_requests(results), len(maps)))
    if args.detail:
        for m, r in zip(maps, results):
            req = requests[m["id"]]
            print(f"\n{'=' * 60}\n{m['id']} ({req['kind']}) 요청: {req['request_text']}")
            for variant in ("strong_gold", "agent"):
                if variant in r and r[variant].worklog:
                    print(f"-- {variant}")
                    print("\n".join(r[variant].worklog))


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--model", action="store_true", help=f"실모델 에이전트도 돌린다(지도 {MODEL_MAP_CAP}개 이하)")
    ap.add_argument("--max-maps", type=int, default=None)
    ap.add_argument("--requests", type=Path, default=None,
                    help="요청 문장 세트(requests.json). 주면 강한 기준선 / +정답 목표 / 에이전트(지휘)를 비교한다")
    ap.add_argument("--detail", action="store_true", help="지도별 작업 기록(이해 → 확인 → 짜기 → … → 끝)도 찍는다. --requests에서만")
    ap.add_argument("--only", default=None, help="지도 id를 쉼표로(예: map_04,map_07). --requests에서만")
    ap.add_argument("--unknown-as-violation", action="store_true", help="휴무 모름을 위반으로 센다(기본은 「확인 필요」)")
    args = ap.parse_args(argv)

    if args.requests:
        return _main_requests(args)
    maps = load_maps(args.data)
    decide = None
    if args.model:
        limit = min(args.max_maps or MODEL_MAP_CAP, MODEL_MAP_CAP)
        maps = maps[:limit]
        from agent.course.deps import ModelDecider          # 실모델 설정(.env)이 필요할 때만 가져온다
        from llm.api import real_course_turn_planner
        decide = ModelDecider(real_course_turn_planner)
    elif args.max_maps:
        maps = maps[: args.max_maps]

    results = [run_variants(scenario_from_map(m, "violation" if args.unknown_as_violation else "check"), decide) for m in maps]
    print(format_table(aggregate(results), len(maps)))
    if decide is not None:
        print(f"모델 토큰(in, out) = {decide.tokens}, 실패 = {len(decide.failures)}")


if __name__ == "__main__":
    main()

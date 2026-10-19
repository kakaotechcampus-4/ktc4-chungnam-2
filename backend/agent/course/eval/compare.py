"""평가 지도에서 세 가지를 비교한다: 초안만 / 코드 기준선 / 에이전트(실모델, 선택).

    cd backend && .venv/bin/python -m agent.course.eval.compare [--data agent/course/eval/data] [--model --max-maps 5]

세 코스 모두 **진짜 영업시간(지도의 hours 전체)** 으로 채점한다 — 에이전트가 조회로 알아낸 것만 아는 상태에서 짠 코스가
실제로는 어떤지 본다. 실모델은 `--model`을 주고 지도를 5개 이하로 제한했을 때만 돈다(비용, 사용자 확인 뒤에 쓴다).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent.course import core, loop
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


def scenario_from_map(m: Mapping[str, Any]) -> Scenario:
    places = tuple(
        Place(p["alias"], f"pin-{p['alias']}", p["source_id"], p["name"], p["category"], p["lat"], p["lng"], frozenset(p["labels"]))
        for p in m["places"]
    )
    trip = Trip(
        places=places,
        days=tuple(date.fromisoformat(d) for d in m["days"]),
        member_constraints=tuple(MemberConstraint(**c) for c in m["member_constraints"]),
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
    confirmed, unknown = core.hard_score(violations)
    return Score(confirmed, unknown, core.soft_scores(sc.trip, course), turns)


def run_variants(sc: Scenario, decide: Optional[Callable] = None) -> dict[str, Score]:
    draft = core.draft_course(sc.trip)
    out = {"draft": score(sc, draft)}
    base = loop.run_loop(initial_state(sc.trip, sc.start_hours, draft), decide=None, hours=sc.gateway)
    out["baseline"] = score(sc, base.best_course, len(base.steps))
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
            "day_balance": _mean([s.soft["day_balance"] for s in rows]),
            "meal_per_day": _mean([s.soft["meal_per_day"] for s in rows]),
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


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--model", action="store_true", help=f"실모델 에이전트도 돌린다(지도 {MODEL_MAP_CAP}개 이하)")
    ap.add_argument("--max-maps", type=int, default=None)
    args = ap.parse_args(argv)

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

    results = [run_variants(scenario_from_map(m), decide) for m in maps]
    print(format_table(aggregate(results), len(maps)))
    if decide is not None:
        print(f"모델 토큰(in, out) = {decide.tokens}, 실패 = {len(decide.failures)}")


if __name__ == "__main__":
    main()

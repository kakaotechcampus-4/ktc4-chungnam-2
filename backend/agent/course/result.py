"""지휘 루프 결과(DirectResult)를 화면용 값으로 바꾼다 — 순수 함수. DB·모델·시간을 모른다.

화면 문장은 전부 코드 템플릿이다. 장소 이름은 문장 안에만 들어가고(별도 칸에 저장하지 않는다), 핀은 `pin_id`로만 가리킨다.
작업 기록(steps)은 `worklog.StepRecord`(구조화된 단계)를 그대로 칸으로 옮긴 것이다 — 글을 다시 읽어 나누지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from agent.course import core, goals as goals_mod
from agent.course.direct import DirectResult
from agent.course.intake import Excluded
from agent.course.korean import attach
from agent.course.worklog import StepRecord

CHECK_TEXT = "영업하는지 알 수 없어요. 가게에 직접 확인해 주세요"


@dataclass(frozen=True)
class CourseView:
    outcome: str
    goals: list[dict[str, Any]]
    unmatched: list[str]
    steps: list[dict[str, Any]]
    days: list[dict[str, Any]]
    violations: list[dict[str, str]]
    checks: list[dict[str, str]]
    excluded: list[dict[str, str]] = field(default_factory=list)


def violation_text(trip: core.Trip, v: core.Violation) -> str:
    """확정 위반 한 건의 문장. 확인 필요(unknown)는 위반이 아니라 checks로 간다."""
    day = core.day_label(trip, v.day)
    if v.kind == "closed":
        return f"{attach(trip.place(v.places[0]).name, '은/는')} {day}에 쉬는 날이에요"
    if v.kind == "member":
        return f"{day} 도보 {v.detail['minutes']}분이 구성원 조건 {v.detail['limit']}분을 넘어요"
    if v.id.startswith("leg:"):     # 도보 구간(대중교통 구간에는 구간 상한이 없다)
        a, b = (trip.place(p).name for p in v.places)
        return f"{day} {a}에서 {b}까지 걸어서 {v.detail['minutes']}분이에요(구간 상한 {v.detail['limit']}분)"
    if v.id.startswith("day:"):
        return f"{day} 이동 합계가 약 {v.detail['minutes']}분이에요(대중교통 포함, 하루 상한 {v.detail['limit']}분)"
    return f"{day} 도보 합계 {v.detail['minutes']}분이에요(하루 상한 {v.detail['limit']}분)"


def build_days(trip: core.Trip, course: core.Course, check_places: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """날짜별 순서와 구간(도보면 도보 분, 대중교통이면 약 분). check_places는 (장소 별칭, 날짜 별칭) — 영업 여부를 모르는 칸."""
    out = []
    for i, day in enumerate(course):
        alias = core.day_alias(i)
        out.append({
            "date": trip.days[i].isoformat(),
            "slots": [{"pin_id": trip.place(p).pin_id, "order": k + 1, "needs_check": (p, alias) in check_places}
                      for k, p in enumerate(day)],
            "legs": [{"from_pin_id": trip.place(a).pin_id, "to_pin_id": trip.place(b).pin_id,
                      "mode": leg.mode, "approx_minutes": leg.minutes}
                     for (a, b), leg in zip(zip(day, day[1:]), core.day_legs(trip, day))],
        })
    return out


def build_view(
    trip: core.Trip, excluded: Sequence[Excluded], goals: Sequence[goals_mod.Goal], unmatched: Sequence[str],
    result: DirectResult, steps: Sequence[StepRecord],
) -> CourseView:
    checks = core.find_checks(trip, result.course, result.state.hours)
    check_cells = {(c.places[0], c.day) for c in checks}
    by_goal = {r.goal.id: r.met for r in result.goal_results}
    return CourseView(
        outcome=result.outcome,
        goals=[{"id": g.id, "kind": g.kind, "label": goals_mod.label(trip, g), "met": by_goal.get(g.id)} for g in goals],
        unmatched=list(unmatched),
        steps=[r.as_dict() for r in steps],
        days=build_days(trip, result.course, check_cells),
        violations=[{"kind": v.kind, "text": violation_text(trip, v)} for v in result.violations if v.status == "confirmed"],
        checks=[{"pin_id": trip.place(c.places[0]).pin_id,
                 "text": f"{attach(trip.place(c.places[0]).name, '은/는')} {core.day_label(trip, c.day)}에 {CHECK_TEXT}"}
                for c in checks],
        excluded=[{"pin_id": e.pin_id, "reason": e.reason, "text": e.message} for e in excluded],
    )

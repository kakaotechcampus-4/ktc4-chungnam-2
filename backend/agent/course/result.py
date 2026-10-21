"""지휘 루프 결과(DirectResult)를 화면용 값으로 바꾼다 — 순수 함수. DB·모델·시간을 모른다.

화면 문장은 전부 코드 템플릿이다. 장소 이름은 문장 안에만 들어가고(별도 칸에 저장하지 않는다), 핀은 `pin_id`로만 가리킨다.
작업 기록(steps)은 `worklog.render`가 만든 줄 "[단계] (누가) 문장"을 칸으로 나눈 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.direct import DirectResult
from agent.course.intake import Excluded
from agent.course.korean import attach

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


ROLES = ("해석", "지휘", "계산", "검증", "결정")
_SIMPLE_WHO = {"모델": "ai", "코드": "code", "사람": "human"}


def _by(who: str) -> tuple[str, Optional[str]]:
    """누가 → (ai|code|human, 자세한 말). 단순한 이름이면 자세한 말이 없다. 섞여 있으면("모델 → 코드") 사람 > 모델 > 코드 순으로
    대표값을 고르고 원문을 by_detail에 남긴다."""
    if who in _SIMPLE_WHO:
        return _SIMPLE_WHO[who], None
    return ("human" if "사람" in who else "ai" if "모델" in who else "code"), who


def _split_line(line: str) -> dict[str, Any]:
    """"[단계] 역할(누가) 문장" → 칸. 누가 안에 괄호가 들어 있을 수 있어("코드(목표 세우기 실패)") 괄호 짝을 센다."""
    if line.startswith("[") and "] " in line:
        stage, rest = line[1:].split("] ", 1)
        role = next((r for r in ROLES if rest.startswith(r + "(")), None)
        if role is not None:
            body = rest[len(role) + 1:]
            depth = 1
            for i, ch in enumerate(body):
                depth += (ch == "(") - (ch == ")")
                if depth == 0:
                    by, detail = _by(body[:i])
                    return {"stage": stage, "role": role, "by": by, "by_detail": detail, "text": body[i + 1:].lstrip()}
    return {"stage": "기록", "role": "지휘", "by": "code", "by_detail": None, "text": line}


def parse_steps(lines: Sequence[str]) -> list[dict[str, Any]]:
    """worklog 줄 → {stage, role, by, by_detail, text}. 형식이 아닌 줄은 단계 "기록"으로 그대로 둔다."""
    return [_split_line(line) for line in lines]


def violation_text(trip: core.Trip, v: core.Violation) -> str:
    """확정 위반 한 건의 문장. 확인 필요(unknown)는 위반이 아니라 checks로 간다."""
    day = core.day_label(trip, v.day)
    if v.kind == "closed":
        return f"{attach(trip.place(v.places[0]).name, '은/는')} {day}에 쉬는 날이에요"
    if v.kind == "member":
        return f"{day} 도보 {v.detail['minutes']}분이 구성원 조건 {v.detail['limit']}분을 넘어요"
    if len(v.places) == 2:     # 구간
        a, b = (trip.place(p).name for p in v.places)
        return f"{day} {a}에서 {b}까지 걸어서 {v.detail['minutes']}분이에요(구간 상한 {v.detail['limit']}분)"
    return f"{day} 도보 합계 {v.detail['minutes']}분이에요(하루 상한 {v.detail['limit']}분)"


def build_days(trip: core.Trip, course: core.Course, check_places: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """날짜별 순서와 구간 도보. check_places는 (장소 별칭, 날짜 별칭) — 영업 여부를 모르는 칸."""
    out = []
    for i, day in enumerate(course):
        alias = core.day_alias(i)
        out.append({
            "date": trip.days[i].isoformat(),
            "slots": [{"pin_id": trip.place(p).pin_id, "order": k + 1, "needs_check": (p, alias) in check_places}
                      for k, p in enumerate(day)],
            "legs": [{"from_pin_id": trip.place(a).pin_id, "to_pin_id": trip.place(b).pin_id,
                      "approx_minutes": core.travel_minutes(trip, a, b)} for a, b in zip(day, day[1:])],
        })
    return out


def build_view(
    trip: core.Trip, excluded: Sequence[Excluded], goals: Sequence[goals_mod.Goal], unmatched: Sequence[str],
    result: DirectResult, lines: Sequence[str],
) -> CourseView:
    checks = core.find_checks(trip, result.course, result.state.hours)
    check_cells = {(c.places[0], c.day) for c in checks}
    by_goal = {r.goal.id: r.met for r in result.goal_results}
    return CourseView(
        outcome=result.outcome,
        goals=[{"id": g.id, "kind": g.kind, "label": goals_mod.label(trip, g), "met": by_goal.get(g.id)} for g in goals],
        unmatched=list(unmatched),
        steps=parse_steps(lines),
        days=build_days(trip, result.course, check_cells),
        violations=[{"kind": v.kind, "text": violation_text(trip, v)} for v in result.violations if v.status == "confirmed"],
        checks=[{"pin_id": trip.place(c.places[0]).pin_id,
                 "text": f"{attach(trip.place(c.places[0]).name, '은/는')} {core.day_label(trip, c.day)}에 {CHECK_TEXT}"}
                for c in checks],
        excluded=[{"pin_id": e.pin_id, "reason": e.reason, "text": e.message} for e in excluded],
    )

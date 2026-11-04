"""점검 결과(review.ReviewResult)와 미배정 장소를 화면용 카드로 바꾼다 — 순수 함수(#1321 PR B, 스펙은 docs/api-spec.yaml CourseFix·CourseChecked·CourseRun.headline).

문장은 전부 코드 템플릿이다. 들어가는 것은 장소 이름(DB)과 날짜 말(코드 표)뿐이고 사용자가 쓴 글은 섞지 않는다(#717).
문제 종류와 세기는 `review.Problem`이 정한다 — 여기서는 새로 판단하지 않는다.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent.course import core, goals as goals_mod, review as review_mod
from agent.course.korean import attach
from agent.course.worklog import problem_text

NOT_FIXED_TEXT = {review_mod.BIG_CHANGE: "크게 바꿔야 해요", review_mod.NOT_WORTH: "고치지 않기로 했어요"}

CHECKED_TEXT = {
    "closed": "쉬는 날에 넣은 곳은 없어요",
    "travel": "도보 구간과 하루 이동이 상한 안이에요",
    "member": "구성원이 고른 도보 상한을 지켜요",
    "condition": "우리 조건과 어긋난 곳은 없어요",
    "goal": "요청한 목표를 모두 지켜요",
    "cluster": "같은 동네가 여러 날로 갈린 곳은 없어요",
    "meal": "식당이 없거나 너무 많은 날은 없어요",
}


def checked_items(result: review_mod.ReviewResult) -> list[dict[str, str]]:
    return [{"kind": k, "text": CHECKED_TEXT[k]} for k in result.checked]


def _resolved_text(trip: core.Trip, goals: Sequence[goals_mod.Goal], p: review_mod.Problem) -> str:
    if p.kind == "closed":
        return f"{trip.place(p.places[0]).name}의 쉬는 날 문제가 풀려요"
    if p.kind in ("travel", "member"):
        return f"{core.day_label(trip, p.day)} 이동 문제가 풀려요"
    if p.kind in ("condition", "goal"):
        goal = next(g for g in goals if g.id == p.goal_id)
        return f"{goals_mod.label(trip, goal)} 목표를 지켜요"
    if p.kind == "cluster":
        return "같은 동네가 가까운 날로 모여요"
    return f"{core.day_label(trip, p.day)} 식사 문제가 풀려요"


def _remaining_text(trip: core.Trip, goals: Sequence[goals_mod.Goal], fix: review_mod.Fix) -> Optional[str]:
    """안을 따라도 그대로 남는 문제 — 옮기는 날에 걸린 것만(그 카드를 반영하고도 그 날에 남는 문제). 다른 날의 문제는 자기 카드가 있다."""
    touched = {core.day_alias(i) for m in fix.moves for i in (m.from_day, m.to_day)}
    moved = {m.place for m in fix.moves}
    left = [p for p in fix.remaining if p.day in touched or moved & set(p.places)]
    if not left:
        return None
    return " · ".join(f"{problem_text(trip, goals, p)} — 그대로예요" for p in left[:2])


def _move(trip: core.Trip, m: review_mod.Move, unassigned: frozenset[str]) -> dict[str, Any]:
    return {
        "pin_id": trip.place(m.place).pin_id,
        "from_date": None if m.place in unassigned else trip.days[m.from_day].isoformat(),
        "to_date": trip.days[m.to_day].isoformat(),
    }


def _card(trip: core.Trip, goals: Sequence[goals_mod.Goal], fix: review_mod.Fix, unassigned: frozenset[str]) -> dict[str, Any]:
    p = fix.problem
    solved = fix.step is not None
    return {
        "kind": p.kind, "strength": p.strength, "text": problem_text(trip, goals, p),
        "moves": [_move(trip, m, unassigned) for m in fix.moves],
        "resolved_text": _resolved_text(trip, goals, p) if solved else None,
        "remaining_text": _remaining_text(trip, goals, fix) if solved else None,
        "not_fixed_reason": None if solved else NOT_FIXED_TEXT.get(fix.not_fixed or review_mod.BIG_CHANGE),
    }


def unassigned_card(trip: core.Trip, course: core.Course, alias: str) -> dict[str, Any]:
    """미배정 장소 하나 — 「○일째에 넣기」. 날은 코스를 짜며 고른 날이다(넣어 둔 날의 이동과 함께 계산한다)."""
    day = core.locate(course, alias)[0]
    place = trip.place(alias)
    return {
        "kind": "unassigned", "strength": "soft",
        "text": f"{attach(place.name, '은/는')} 아직 날짜에 넣지 않았어요",
        "moves": [{"pin_id": place.pin_id, "from_date": None, "to_date": trip.days[day].isoformat()}],
        "resolved_text": f"{core.day_label(trip, core.day_alias(day))}에 두는 안이에요",
        "remaining_text": None, "not_fixed_reason": None,
    }


def build_fixes(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], result: review_mod.ReviewResult,
    course: core.Course, unassigned: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """고칠 점 카드. 하드 먼저, 그다음 미배정, 그다음 선호(응답 CourseRun.fixes 설명). id는 fix_1 … 순서대로 붙인다."""
    gone = frozenset(unassigned)
    hard = [_card(trip, goals, f, gone) for f in result.fixes if f.problem.strength == "hard"]
    soft = [_card(trip, goals, f, gone) for f in result.fixes if f.problem.strength == "soft"]
    cards = [*hard, *(unassigned_card(trip, course, a) for a in unassigned), *soft]
    return [{"id": f"fix_{i + 1}", **c} for i, c in enumerate(cards)]


def headline(mode: str, *, n_fixes: int, n_unassigned: int = 0) -> str:
    """결과 화면 머리 문구(모드마다 다른 서버 템플릿). 버튼 이름은 모드와 관계없이 「AI 코스」다."""
    if mode == "review":
        return "일정을 점검했어요. 고칠 점이 없어요" if n_fixes == 0 else f"일정을 점검했어요. 고칠 점 {n_fixes}개"
    if mode == "fill":
        rest = n_fixes - n_unassigned
        tail = f" 고칠 점 {rest}개도 있어요." if rest > 0 else ""
        return f"넣어 둔 일정은 그대로 두고 남은 {n_unassigned}곳을 나눠 봤어요.{tail}"
    return "날짜별 코스를 짰어요"

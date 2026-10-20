"""요청 목표(명세 8.2) — 점수와 매개변수 검증. 순수 함수만 둔다. 점수는 코드가 계산하고 모델은 목표 종류와 별칭만 고른다.

목표 6종: day_indoor, night_end, daily_walk_low, day_light, place_on_day, together.
라벨이 비어 있는 장소는 "라벨을 모른다"로 보고 그 목표 점수에서 뺀다(지어내지 않는다). 판단할 대상이 하나도 없으면
충족 여부는 None(판단할 수 없음)이고 충족 수·간격 합계에서 빠진다.

충족 여부(met)는 코드의 임계값이다: 실내 비율 ≥ INDOOR_MET_RATIO, 하루 도보 최대 ≤ DAILY_WALK_LOW_MAX_MIN, 하루 장소 수 ≤ 평균−1.
간격(gap)은 못 미친 정도를 0~1로 나눈 값이다 — 한 수씩 올리는 규칙이 "충족 직전까지 좋아지는 수"를 알아보게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from agent.course import core
from agent.course.constants import (
    DAILY_WALK_LOW_MAX_MIN, GOALS_MAX, INDOOR_LABEL, INDOOR_MET_RATIO, NIGHT_LABEL,
)
from agent.course.core import Course, Trip

GoalKind = Literal["day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together"]
GOAL_KINDS: tuple[str, ...] = ("day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together")


@dataclass(frozen=True)
class Goal:
    kind: str
    day: Optional[str] = None            # d1 …
    places: tuple[str, ...] = ()         # p1 …

    @property
    def id(self) -> str:
        return ":".join([self.kind, *([self.day] if self.day else []), *(["+".join(self.places)] if self.places else [])])


@dataclass(frozen=True)
class GoalResult:
    goal: Goal
    met: Optional[bool]                  # None = 판단할 수 없다(라벨을 아는 장소가 없다)
    gap: float                           # 0이면 충족. 판단할 수 없으면 0
    value: Optional[float]               # 원래 점수(비율·분·장소 수·1/0). 판단할 수 없으면 None


def normalize(trip: Trip, kind: str, day: Optional[str], places: Sequence[str]) -> tuple[Optional[Goal], Optional[str]]:
    """매개변수를 검사해 Goal을 만든다. 안 되면 (None, 이유). 종류에 필요 없는 매개변수는 버린다."""
    if kind not in GOAL_KINDS:
        return None, f"모르는 목표 종류 {kind}"
    needs_day = kind in ("day_indoor", "night_end", "day_light", "place_on_day")
    n_places = {"place_on_day": 1, "together": 2}.get(kind, 0)
    if needs_day and (day is None or core.day_index(trip, day) is None):
        return None, f"{kind}에는 여행 기간 안의 날짜가 필요하다"
    if len(places) < n_places:
        return None, f"{kind}에는 장소 {n_places}개가 필요하다"
    chosen = tuple(places[:n_places])
    if any(not trip.has_place(p) for p in chosen):
        return None, "없는 장소"
    if kind == "together" and chosen[0] == chosen[1]:
        return None, "같은 장소끼리는 묶을 수 없다"
    return Goal(kind, day if needs_day else None, chosen), None


def _known(trip: Trip, place: str) -> bool:
    return bool(trip.place(place).labels)


def day_light_cap(trip: Trip) -> int:
    return max(1, len(trip.places) // len(trip.days) - 1)


def evaluate(trip: Trip, course: Course, goal: Goal) -> GoalResult:
    unknown = GoalResult(goal, None, 0.0, None)
    if goal.kind in ("day_indoor", "night_end", "day_light"):
        i = core.day_index(trip, goal.day or "")
        day = course[i] if i is not None else ()
        if goal.kind == "day_light":
            cap = day_light_cap(trip)
            return GoalResult(goal, len(day) <= cap, max(0, len(day) - cap) / cap, float(len(day)))
        if not day:
            return unknown
        if goal.kind == "day_indoor":
            known = [p for p in day if _known(trip, p)]
            if not known:
                return unknown
            ratio = sum(INDOOR_LABEL in trip.place(p).labels for p in known) / len(known)
            return GoalResult(goal, ratio >= INDOOR_MET_RATIO, max(0.0, INDOOR_MET_RATIO - ratio), ratio)
        if not _known(trip, day[-1]):
            return unknown
        hit = NIGHT_LABEL in trip.place(day[-1]).labels
        return GoalResult(goal, hit, 0.0 if hit else 1.0, 1.0 if hit else 0.0)
    if goal.kind == "daily_walk_low":
        worst = max((core.day_travel(trip, d) for d in course), default=0)
        return GoalResult(goal, worst <= DAILY_WALK_LOW_MAX_MIN,
                          max(0, worst - DAILY_WALK_LOW_MAX_MIN) / DAILY_WALK_LOW_MAX_MIN, float(worst))
    if goal.kind == "place_on_day":
        i = core.day_index(trip, goal.day or "")
        hit = i is not None and goal.places[0] in course[i]
        return GoalResult(goal, hit, 0.0 if hit else 1.0, 1.0 if hit else 0.0)
    a, b = goal.places                                    # together
    same = any(a in d and b in d for d in course)
    return GoalResult(goal, same, 0.0 if same else 1.0, 1.0 if same else 0.0)


def evaluate_all(trip: Trip, course: Course, goals: Sequence[Goal]) -> tuple[GoalResult, ...]:
    return tuple(evaluate(trip, course, g) for g in goals)


def ordered(goals: Sequence[Goal], priority: Sequence[str] = ()) -> tuple[Goal, ...]:
    """우선순위(목표 id 순서)대로 늘어놓는다. 목록에 없는 목표는 원래 순서로 뒤에 붙는다."""
    rank = {gid: i for i, gid in enumerate(priority)}
    return tuple(sorted(goals, key=lambda g: rank.get(g.id, len(rank))))      # sorted는 안정 정렬


def key_part(trip: Trip, course: Course, goals: Sequence[Goal], priority: Sequence[str] = ()) -> tuple:
    """강한 기준선의 사전식 비교에 끼우는 부분: (충족하지 못한 목표 수, 우선순위순 미충족 표시, 우선순위순 간격).
    판단할 수 없는 목표(met=None)는 못 이룬 것(간격 1)으로 센다 — 안 그러면 라벨 모르는 장소를 끌어들여 목표를 "판단 불가"로 만들어
    점수를 피하는 수가 이득이 된다. 목표가 없으면 빈 값이라 기존 비교와 같다."""
    results = [(r.met is True, 1.0 if r.met is None else r.gap)
               for r in evaluate_all(trip, course, ordered(goals, priority))]
    return (
        sum(not met for met, _ in results),
        tuple(not met for met, _ in results),
        tuple(round(gap, 4) for _, gap in results),
    )


def met_count(trip: Trip, course: Course, goals: Sequence[Goal]) -> tuple[int, int]:
    """(충족한 목표 수, 판단할 수 있는 목표 수)."""
    results = [r for r in evaluate_all(trip, course, goals) if r.met is not None]
    return sum(bool(r.met) for r in results), len(results)


def truncate(goals: Sequence[Goal]) -> tuple[Goal, ...]:
    seen: dict[str, Goal] = {}
    for g in goals:
        seen.setdefault(g.id, g)
    return tuple(seen.values())[:GOALS_MAX]


# ---- 목표 세우기 입력과 검증 (명세 8.2) ----

@dataclass(frozen=True)
class VerifiedGoals:
    goals: tuple[Goal, ...]
    unmatched: tuple[str, ...]              # 화면에 "반영하지 못했어요"로 보일 조각(원문 부분 문자열)
    dropped: tuple[str, ...]                # 검증에서 떨어진 목표의 이유(시도 기록용, 화면에 쓰지 않는다)


def goals_input(trip: Trip, request_text: str) -> dict:
    """llm.course_set_goals 입력. 요청 속 장소 이름을 별칭으로 바꾸려면 name이 필요해 이름을 넣는다(지휘 턴 입력에는 이름이 없다)."""
    return {
        "request": request_text,
        "days": [{"day": core.day_alias(i), "weekday": "월화수목금토일"[d.weekday()] + "요일"} for i, d in enumerate(trip.days)],
        "first_day": core.day_alias(0),
        "last_day": core.day_alias(len(trip.days) - 1),
        "places": [{"place": p.alias, "name": p.name, "category": p.category} for p in trip.places],
    }


def verify_goal_set(trip: Trip, request_text: str, goal_set) -> VerifiedGoals:
    """모델이 낸 목표(CourseGoalSet)를 코드가 검증한다: 종류별 매개변수, 별칭, quote가 요청 원문의 부분 문자열인지.
    떨어진 목표는 버리고, 그 quote가 원문 조각이면 unmatched로 옮긴다. unmatched도 원문 부분 문자열만 남긴다."""
    goals: list[Goal] = []
    dropped: list[str] = []
    unmatched: list[str] = []
    for g in goal_set.goals:
        problem = None
        if g.source != "request":
            problem = "요청이 아닌 근거"
        elif not g.quote.strip() or g.quote not in request_text:
            problem = "quote가 원문에 없다"
        goal, why = normalize(trip, g.kind, g.day, g.places) if problem is None else (None, problem)
        if goal is None:
            dropped.append(f"{g.kind}: {why}")
            if g.quote.strip() and g.quote in request_text:
                unmatched.append(g.quote)
        else:
            goals.append(goal)
    unmatched += [u for u in goal_set.unmatched if u.strip() and u in request_text]
    return VerifiedGoals(truncate(goals), tuple(dict.fromkeys(unmatched)), tuple(dropped))


def label(trip: Trip, goal: Goal) -> str:
    """화면 문장 조각(코드 템플릿). 장소 이름은 화면에서만 쓴다."""
    day = core.day_label(trip, goal.day) if goal.day else ""
    names = [trip.place(p).name for p in goal.places]
    return {
        "day_indoor": f"{day}은 실내 위주로",
        "night_end": f"{day} 마지막은 야경 명소",
        "daily_walk_low": "하루 걷는 시간 줄이기",
        "day_light": f"{day}은 여유 있게",
        "place_on_day": f"{names[0] if names else ''}을(를) {day}에" if goal.kind == "place_on_day" else "",
        "together": f"{' · '.join(names)} 같은 날" if goal.kind == "together" else "",
    }[goal.kind]

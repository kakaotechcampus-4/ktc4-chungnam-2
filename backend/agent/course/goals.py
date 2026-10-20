"""요청 목표(명세 8.2) — 점수와 매개변수 검증. 순수 함수만 둔다. 점수는 코드가 계산하고 모델은 목표 종류와 별칭만 고른다.

목표 6종: day_indoor, night_end, daily_walk_low, day_light, place_on_day, together.
라벨이 비어 있는 장소는 "라벨을 모른다"로 보고 그 목표 점수에서 뺀다(지어내지 않는다). 판단할 대상이 하나도 없으면
충족 여부는 None(판단할 수 없음)이고 충족 수·간격 합계에서 빠진다.

충족 여부(met)는 코드의 임계값이다: 실내 비율 ≥ INDOOR_MET_RATIO, 하루 도보 최대 ≤ DAILY_WALK_LOW_MAX_MIN, 하루 장소 수 ≤ 평균−1.
간격(gap)은 못 미친 정도를 0~1로 나눈 값이다 — 한 수씩 올리는 규칙이 "충족 직전까지 좋아지는 수"를 알아보게 한다.
"""

from __future__ import annotations

import math
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


def key_part(
    trip: Trip, course: Course, goals: Sequence[Goal], priority: Sequence[str] = (), strict: bool = False,
) -> tuple:
    """강한 기준선의 사전식 비교에 끼우는 부분: (충족하지 못한 목표 수, 우선순위순 미충족 표시, 우선순위순 간격).
    strict=True면 수를 맨 뒤로 보내 (우선순위순 미충족 표시, 간격, 수) — 맨 앞 목표를 다른 목표보다 먼저 지키는 "집중" 후보를 만든다.
    판단할 수 없는 목표(met=None)는 못 이룬 것(간격 1)으로 센다 — 안 그러면 라벨 모르는 장소를 끌어들여 목표를 "판단 불가"로 만들어
    점수를 피하는 수가 이득이 된다. 목표가 없으면 빈 값이라 기존 비교와 같다."""
    results = [(r.met is True, 1.0 if r.met is None else r.gap)
               for r in evaluate_all(trip, course, ordered(goals, priority))]
    unmet = sum(not met for met, _ in results)
    flags, gaps = tuple(not met for met, _ in results), tuple(round(gap, 4) for _, gap in results)
    return (flags, gaps, unmet) if strict else (unmet, flags, gaps)


def met_count(trip: Trip, course: Course, goals: Sequence[Goal]) -> tuple[int, int]:
    """(충족한 목표 수, 목표 수). 판단할 수 없는 목표(met=None)도 분모에 넣고 못 이룬 것으로 센다 — 안 그러면 방식마다 분모가
    달라져 비교가 흐려지고, 라벨 모르는 장소로 목표를 피하는 코스가 유리해진다(key_part와 같은 규칙). 몇 개가 판단 불가인지는
    undecidable_count로 따로 본다."""
    results = evaluate_all(trip, course, goals)
    return sum(r.met is True for r in results), len(results)


def undecidable_count(trip: Trip, course: Course, goals: Sequence[Goal]) -> int:
    return sum(r.met is None for r in evaluate_all(trip, course, goals))


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


# ---- 데이터 확인 (check_goals, pivot 8.2절) ----
# 코스를 짜기 전에 코드가 "이 리스트로 이 목표가 가능한가"를 확인한다. 라벨을 모르는 장소(labels 비어 있음)는 "라벨을 아는 장소 수"에서 뺀다.

NO_NIGHT_PLACE = "NO_NIGHT_PLACE"
NIGHT_PLACE_CLOSED_ON_DAY = "NIGHT_PLACE_CLOSED_ON_DAY"
FEW_INDOOR = "FEW_INDOOR"
PLACE_CLOSED_ON_DAY = "PLACE_CLOSED_ON_DAY"
NO_COMMON_OPEN_DAY = "NO_COMMON_OPEN_DAY"
LABELS_UNKNOWN = "LABELS_UNKNOWN"

_CHECK_SENTENCES = {
    NO_NIGHT_PLACE: "야경 명소가 이 리스트에 없어요",
    NIGHT_PLACE_CLOSED_ON_DAY: "야경 명소가 그날 모두 쉬어요",
    FEW_INDOOR: "실내 장소가 적어서 그날을 실내 위주로 채우기 어려워요",
    PLACE_CLOSED_ON_DAY: "그 장소가 그날 쉬어요",
    NO_COMMON_OPEN_DAY: "두 장소가 함께 영업하는 날이 없어요",
    LABELS_UNKNOWN: "라벨을 아는 장소가 없어 판단할 수 없어요",
}


def _closed_days(trip: Trip, hours, place: str) -> list[str]:
    return [core.day_alias(i) for i, d in enumerate(trip.days) if core.status_on(hours, place, d) == "closed"]


def check_goal(trip: Trip, hours, goal: Goal) -> dict:
    """{"id", "feasible": True/False/None, "reasons": [코드], "facts": {...}}. None은 데이터로 알 수 없다는 뜻이다."""
    facts: dict = {}
    reasons: list[str] = []
    feasible: Optional[bool] = True
    labeled = [p.alias for p in trip.places if p.labels]
    if goal.kind == "night_end":
        night = [p.alias for p in trip.places if NIGHT_LABEL in p.labels]
        facts = {"night_places": len(night), "labeled_places": len(labeled),
                 "night_closed_days": {p: _closed_days(trip, hours, p) for p in night if _closed_days(trip, hours, p)}}
        if not labeled:
            feasible, reasons = None, [LABELS_UNKNOWN]
        elif not night:
            feasible, reasons = False, [NO_NIGHT_PLACE]
        elif all(goal.day in _closed_days(trip, hours, p) for p in night):
            feasible, reasons = False, [NIGHT_PLACE_CLOSED_ON_DAY]
    elif goal.kind == "day_indoor":
        indoor = [p.alias for p in trip.places if INDOOR_LABEL in p.labels]
        per_day = -(-len(trip.places) // len(trip.days))
        need = math.ceil(INDOOR_MET_RATIO * per_day - 1e-9)                 # 하루 평균 장소 수의 70%를 올림
        facts = {"indoor_places": len(indoor), "labeled_places": len(labeled), "needed": need,
                 "indoor_closed_on_day": [p for p in indoor if goal.day in _closed_days(trip, hours, p)]}
        if not labeled:
            feasible, reasons = None, [LABELS_UNKNOWN]
        elif len(indoor) - len(facts["indoor_closed_on_day"]) < need:
            feasible, reasons = False, [FEW_INDOOR]
    elif goal.kind == "place_on_day":
        closed = goal.day in _closed_days(trip, hours, goal.places[0])
        status = core.status_on(hours, goal.places[0], trip.days[core.day_index(trip, goal.day) or 0])
        facts = {"place_closed_days": _closed_days(trip, hours, goal.places[0]), "status_on_day": status}
        if closed:
            feasible, reasons = False, [PLACE_CLOSED_ON_DAY]
        elif status == "unknown":
            feasible = None
    elif goal.kind == "together":
        a, b = goal.places
        open_both = [core.day_alias(i) for i, d in enumerate(trip.days)
                     if core.status_on(hours, a, d) != "closed" and core.status_on(hours, b, d) != "closed"]
        facts = {"common_open_days": open_both}
        if not open_both:
            feasible, reasons = False, [NO_COMMON_OPEN_DAY]
    else:                                                                # daily_walk_low, day_light: 데이터로 막히는 일이 없다
        feasible = True
    return {"id": goal.id, "feasible": feasible, "reasons": reasons, "facts": facts}


def check_goals(trip: Trip, hours, goals: Sequence[Goal]) -> tuple[dict, ...]:
    return tuple(check_goal(trip, hours, g) for g in goals)


def check_sentence(trip: Trip, check: dict, goal: Goal) -> str:
    """작업 기록의 "확인: …" 한 줄(코드 템플릿)."""
    head = label(trip, goal)
    if check["feasible"] is True:
        return f"{head}: 가능해 보여요"
    why = " · ".join(_CHECK_SENTENCES[r] for r in check["reasons"]) or "영업 여부를 몰라 확인이 필요해요"
    return f"{head}: {why}"


def short_label(trip: Trip, goal: Goal, met: Optional[bool]) -> str:
    """질문 카드에서 후보마다 붙는 짧은 문구."""
    names = [trip.place(p).name for p in goal.places]
    yes, no = {
        "night_end": ("야경 지킴", "야경 없음"),
        "day_indoor": ("실내 위주", "실내 아님"),
        "day_light": ("여유 있게", "빽빽함"),
        "place_on_day": (f"{names[0] if names else ''} 방문", f"{names[0] if names else ''} 못 감"),
        "together": ("같은 날", "다른 날"),
        "daily_walk_low": ("덜 걸음", "많이 걸음"),
    }[goal.kind]
    return yes if met else no


# ---- 쉬는 날에 걸린 목표 — 옮길 수 있는 날 찾기와 목표 고치기 ----

CLOSURE_CODES = (PLACE_CLOSED_ON_DAY, NIGHT_PLACE_CLOSED_ON_DAY)


def alternative_days(trip: Trip, hours, goal: Goal) -> list[str]:
    """쉬는 날에 걸린 목표(place_on_day, night_end)를 옮길 수 있는 여행 날짜. 확실히 여는 날을 먼저 쓰고, 하나도 없으면 영업 여부를 모르는
    날을 쓴다. 쉬는 날은 넣지 않는다. 날짜 순서대로다."""
    def status(day_index: int) -> str:
        d = trip.days[day_index]
        if goal.kind == "place_on_day":
            return core.status_on(hours, goal.places[0], d)
        states = [core.status_on(hours, p.alias, d) for p in trip.places if NIGHT_LABEL in p.labels]
        return "open" if "open" in states else ("unknown" if "unknown" in states else "closed")

    statuses = {core.day_alias(i): status(i) for i in range(len(trip.days))}
    for wanted in ("open", "unknown"):
        days = [d for d, st in statuses.items() if st == wanted and d != goal.day]
        if days:
            return days
    return []


def retarget(goal: Goal, day: str) -> Goal:
    return Goal(goal.kind, day, goal.places)

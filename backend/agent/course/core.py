"""동선 에이전트 기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·모델·시간을 모른다.

초안 배치(명세 14.4), 위반 판정(7.2 — 범위 B), 부드러운 목표 점수(8절), 수리 적용과 검사(7.2),
화면 문장 검증과 렌더(13절), 결과 판정(11.3)이 여기 있다.

코스는 `tuple[tuple[str, ...], ...]`다 — 날짜 순서대로, 그날 방문할 장소 별칭(p1, p2 …)의 순서.
장소 하나는 코스에 한 번만 나온다. 날짜 별칭은 1부터 센다(d1 = 여행 첫날).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Mapping, Optional, Sequence

from agent.course.constants import (
    CAFE_CATEGORY,
    CLUSTER_THRESHOLD_M,
    DAY_TRAVEL_MAX_MIN,
    FORBIDDEN_PHRASES,
    LEG_MAX_MIN,
    MEAL_CATEGORY,
    MEALS_PER_DAY_MAX,
    NIGHT_LABEL,
    THOUGHT_MAX_CHARS,
)
from agent.course.schemas import Move, MoveDay, ReorderDay, Swap
from common.geo import Point, approx_walk_minutes, haversine_distance_m, nearest_neighbor_order

Course = tuple[tuple[str, ...], ...]
DayStatus = Literal["open", "closed", "unknown"]
# 장소 별칭 → 요일(월=0 … 일=6) → 상태. 장소나 요일이 없으면 unknown이다(지어내지 않는다).
Hours = Mapping[str, Mapping[int, DayStatus]]


# ---- 입력 ----

@dataclass(frozen=True)
class Place:
    alias: str            # p1, p2 … (모델이 보는 이름)
    pin_id: str
    place_id: str         # 자체 DB 장소 id — 영업시간 조회에 쓴다. 모델 입력에는 넣지 않는다
    name: str
    category: str
    lat: float
    lng: float
    labels: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MemberConstraint:
    """요청자가 고른 구성원 제약(명세 14.2). 범위 B에서는 하루 도보 상한만 쓴다."""
    kind: Literal["daily_walk_max"]
    value: int                      # 분
    day: Optional[str] = None       # 날짜 별칭. None이면 모든 날


@dataclass(frozen=True)
class Trip:
    """한 run 동안 바뀌지 않는 입력. 장소 순서는 확정 리스트에 들어온 순서다(초안 배치가 안정적이도록)."""
    places: tuple[Place, ...]
    days: tuple[date, ...]
    member_constraints: tuple[MemberConstraint, ...] = ()
    # 휴무를 모르는 장소를 위반 목록에 넣을지("violation"), 위반 밖 「확인 필요」 목록으로 따로 둘지("check").
    # 확인 필요는 위반이 아니라 하드 점수·채택 거부에 영향이 없고, 결과 판정(solved_with_checks)에만 남는다.
    unknown_hours: Literal["violation", "check"] = "violation"
    _by_alias: dict[str, Place] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_alias", {p.alias: p for p in self.places})
        if len(self._by_alias) != len(self.places):
            raise ValueError("장소 별칭이 겹친다")
        if not self.days:
            raise ValueError("여행 날짜가 없다")

    def place(self, alias: str) -> Place:
        return self._by_alias[alias]

    def has_place(self, alias: str) -> bool:
        return alias in self._by_alias

    @property
    def day_aliases(self) -> tuple[str, ...]:
        return tuple(day_alias(i) for i in range(len(self.days)))


def day_alias(index: int) -> str:
    return f"d{index + 1}"


def day_index(trip: Trip, alias: str) -> Optional[int]:
    """날짜 별칭 → 0부터 센 위치. 형식이 틀리거나 기간 밖이면 None."""
    m = re.fullmatch(r"d([1-9][0-9]*)", alias)
    if not m:
        return None
    i = int(m.group(1)) - 1
    return i if i < len(trip.days) else None


def status_on(hours: Hours, place: str, d: date) -> DayStatus:
    return hours.get(place, {}).get(d.weekday(), "unknown")


# ---- 이동 ----

def travel_minutes(trip: Trip, a: str, b: str) -> int:
    pa, pb = trip.place(a), trip.place(b)
    return approx_walk_minutes(haversine_distance_m(pa.lat, pa.lng, pb.lat, pb.lng))


def day_travel(trip: Trip, places: Sequence[str]) -> int:
    return sum(travel_minutes(trip, a, b) for a, b in zip(places, places[1:]))


def course_travel(trip: Trip, course: Course) -> int:
    return sum(day_travel(trip, day) for day in course)


# ---- 초안 배치 (명세 14.4) ----

def _clusters(trip: Trip) -> list[list[Place]]:
    """단일 연결 묶기(거리 임계값). shortlist/routing.py와 같은 기준이다 — 두 곳을 합치는 일은 #226/#274."""
    places = list(trip.places)
    parent = list(range(len(places)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(places)):
        for j in range(i + 1, len(places)):
            a, b = places[i], places[j]
            if haversine_distance_m(a.lat, a.lng, b.lat, b.lng) <= CLUSTER_THRESHOLD_M:
                parent[find(i)] = find(j)

    groups: dict[int, list[Place]] = {}
    for i, p in enumerate(places):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())   # 첫 등장 순서 그대로


def draft_course(trip: Trip) -> Course:
    """같은 입력이면 항상 같은 코스. 묶음은 쪼개지 않는다 — 쪼개는 건 수리(이월)의 몫이다.
    큰 묶음부터, 지금 장소가 가장 적은 날(동점이면 앞 날짜)에 넣고, 하루 안은 최근접 이웃 순서다."""
    clusters = sorted(enumerate(_clusters(trip)), key=lambda ic: (-len(ic[1]), ic[0]))
    days: list[list[Place]] = [[] for _ in trip.days]
    for _, cluster in clusters:
        target = min(range(len(days)), key=lambda i: (len(days[i]), i))
        days[target].extend(cluster)
    return tuple(
        tuple(nearest_neighbor_order([Point(p.alias, p.lat, p.lng) for p in day])) for day in days
    )


# ---- 위반 판정 (명세 7.2, 범위 B) ----

@dataclass(frozen=True)
class Violation:
    id: str                                   # 예: closed:p4:d2, leg:p1-p2:d1, day:d1, member:d1
    kind: Literal["closed", "travel", "member"]
    status: Literal["confirmed", "unknown"]   # unknown = 결측(판정할 데이터가 없다)
    day: str
    places: tuple[str, ...]
    detail: Mapping[str, int] = field(default_factory=dict)


def find_violations(trip: Trip, course: Course, hours: Hours) -> tuple[Violation, ...]:
    """같은 입력이면 같은 출력, 순서도 같다(날짜 → 종류 → 장소 순)."""
    out: list[Violation] = []
    for i, day in enumerate(course):
        d, da = trip.days[i], day_alias(i)
        for p in day:
            status = status_on(hours, p, d)
            if status == "unknown" and trip.unknown_hours == "check":
                continue                                  # find_checks가 따로 돌려준다
            if status != "open":
                out.append(Violation(
                    f"closed:{p}:{da}", "closed", "confirmed" if status == "closed" else "unknown", da, (p,),
                ))
        for a, b in zip(day, day[1:]):
            minutes = travel_minutes(trip, a, b)
            if minutes > LEG_MAX_MIN:
                out.append(Violation(
                    f"leg:{a}-{b}:{da}", "travel", "confirmed", da, (a, b),
                    {"minutes": minutes, "limit": LEG_MAX_MIN},
                ))
        total = day_travel(trip, day)
        if total > DAY_TRAVEL_MAX_MIN:
            out.append(Violation(
                f"day:{da}", "travel", "confirmed", da, tuple(day), {"minutes": total, "limit": DAY_TRAVEL_MAX_MIN},
            ))
        for c in trip.member_constraints:
            if c.day in (None, da) and total > c.value:
                out.append(Violation(
                    f"member:{da}", "member", "confirmed", da, tuple(day), {"minutes": total, "limit": c.value},
                ))
    return tuple(out)


def find_checks(trip: Trip, course: Course, hours: Hours) -> tuple[Violation, ...]:
    """「확인 필요」 — 그날 영업하는지 모르는 장소. unknown_hours 설정과 상관없이 늘 같은 결과다."""
    return tuple(
        Violation(f"closed:{p}:{day_alias(i)}", "closed", "unknown", day_alias(i), (p,))
        for i, day in enumerate(course)
        for p in day
        if status_on(hours, p, trip.days[i]) == "unknown"
    )


def hard_summary(trip: Trip, hours: Hours, course: Course, violations: Sequence[Violation]) -> dict[str, int]:
    """모델과 도구 결과에 보이는 하드 요약. 위반 모드는 {confirmed, unknown}, 확인 필요 모드는 {confirmed, checks}."""
    confirmed, unknown = hard_score(violations)
    if trip.unknown_hours == "check":
        return {"confirmed": confirmed, "checks": len(find_checks(trip, course, hours))}
    return {"confirmed": confirmed, "unknown": unknown}


def hard_score(violations: Sequence[Violation]) -> tuple[int, int]:
    """(확정 위반 수, 결측 수). 사전식으로 비교하고 낮을수록 좋다."""
    confirmed = sum(v.status == "confirmed" for v in violations)
    return confirmed, len(violations) - confirmed


# ---- 부드러운 목표 (명세 8절, 범위 B) ----

def soft_scores(trip: Trip, course: Course) -> dict[str, Optional[float]]:
    """코드가 계산만 한다. 가중치로 합치지 않는다 — 절충은 모델이 판단한다. 대상이 없는 목표는 None."""
    cat = {p.alias: p.category for p in trip.places}
    meal_pairs = sum(
        cat[a] == MEAL_CATEGORY and cat[b] == MEAL_CATEGORY for day in course for a, b in zip(day, day[1:])
    )
    meal_excess = sum(max(0, sum(cat[p] == MEAL_CATEGORY for p in day) - MEALS_PER_DAY_MAX) for day in course)

    cafes = [(day, i) for day in course for i, p in enumerate(day) if cat[p] == CAFE_CATEGORY]
    cafe_after_meal = (
        sum(i > 0 and cat[day[i - 1]] == MEAL_CATEGORY for day, i in cafes) / len(cafes) if cafes else None
    )
    night = [(day, p) for day in course for p in day if NIGHT_LABEL in trip.place(p).labels]
    night_last = sum(day[-1] == p for day, p in night) / len(night) if night else None

    counts = [len(day) for day in course]
    return {
        "meal_spacing": meal_pairs,
        "meal_per_day": meal_excess,
        "cafe_after_meal": cafe_after_meal,
        "night_last": night_last,
        "day_balance": max(counts) - min(counts),
        "travel_total": course_travel(trip, course),
    }


# ---- 수리 적용과 검사 ----

class MoveError(ValueError):
    """수리를 적용할 수 없다. code는 도구 오류 코드(명세 7절)로 그대로 모델에 돌아간다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def locate(course: Course, place: str) -> tuple[int, int]:
    for i, day in enumerate(course):
        if place in day:
            return i, day.index(place)
    raise MoveError("INVALID_ID", f"{place}는 코스에 없다")


def _check_lock(trip: Trip, locks: Mapping[str, str], place: str, to_day_index: int) -> None:
    locked = locks.get(place)
    if locked is not None and locked != day_alias(to_day_index):
        raise MoveError("LOCKED", f"{place}는 {locked}에 고정돼 있다")


def best_position(trip: Trip, day: Sequence[str], place: str) -> int:
    """그날 이동 합계가 가장 짧아지는 자리. 동점이면 앞자리."""
    return min(
        range(len(day) + 1),
        key=lambda k: (day_travel(trip, [*day[:k], place, *day[k:]]), k),
    )


def apply_move(trip: Trip, course: Course, move: Move, locks: Mapping[str, str]) -> Course:
    """수리를 적용한 새 코스를 돌려준다. 원래 코스는 바꾸지 않는다. 적용할 수 없으면 MoveError."""
    days = [list(day) for day in course]

    if isinstance(move, Swap):
        for p in (move.a, move.b):
            if not trip.has_place(p):
                raise MoveError("INVALID_ID", f"{p}는 없는 장소다")
        if move.a == move.b:
            raise MoveError("INVALID_MOVE", "같은 장소끼리는 바꿀 수 없다")
        (da, ia), (db, ib) = locate(course, move.a), locate(course, move.b)
        _check_lock(trip, locks, move.a, db)
        _check_lock(trip, locks, move.b, da)
        days[da][ia], days[db][ib] = move.b, move.a

    elif isinstance(move, MoveDay):
        if not trip.has_place(move.place):
            raise MoveError("INVALID_ID", f"{move.place}는 없는 장소다")
        to = day_index(trip, move.to_day)
        if to is None:
            raise MoveError("INVALID_ID", f"{move.to_day}는 여행 기간 밖이다")
        frm, idx = locate(course, move.place)
        if frm == to:
            raise MoveError("INVALID_MOVE", f"{move.place}는 이미 {move.to_day}에 있다")
        _check_lock(trip, locks, move.place, to)
        days[frm].pop(idx)
        if move.position is None:
            pos = best_position(trip, days[to], move.place)
        elif 0 <= move.position <= len(days[to]):
            pos = move.position
        else:
            raise MoveError("INVALID_MOVE", f"자리 {move.position}는 {move.to_day}의 범위 밖이다")
        days[to].insert(pos, move.place)

    elif isinstance(move, ReorderDay):
        i = day_index(trip, move.day)
        if i is None:
            raise MoveError("INVALID_ID", f"{move.day}는 여행 기간 밖이다")
        if sorted(move.places) != sorted(course[i]):
            raise MoveError("INVALID_MOVE", f"{move.day}의 장소를 하나씩 빠짐없이 다시 늘어놓아야 한다")
        days[i] = list(move.places)

    else:  # 스키마가 막는다. 새 수리 종류를 추가하고 여기를 빠뜨리면 바로 드러나게 한다
        raise MoveError("INVALID_MOVE", f"모르는 수리 종류 {type(move).__name__}")

    return tuple(tuple(day) for day in days)


def open_days(trip: Trip, hours: Hours, place: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"open": [], "closed": [], "unknown": []}
    for i, d in enumerate(trip.days):
        out[status_on(hours, place, d)].append(day_alias(i))
    return out


# ---- 화면 문장 (명세 13절) ----

_ALIAS = re.compile(r"\{([pd][1-9][0-9]*)\}")
_ORDINALS = ("첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째", "열째")
_WEEKDAYS = "월화수목금토일"


def thought_problem(trip: Trip, text: str) -> Optional[str]:
    """생각 한 줄을 화면에 내보내도 되는지. 안 되면 이유, 되면 None.
    숫자는 별칭 슬롯({p4}, {d2}) 밖에 쓸 수 없다 — 모델이 쓴 숫자를 그대로 내보내지 않는다."""
    if not text.strip():
        return "빈 문장"
    if len(text) > THOUGHT_MAX_CHARS:
        return "너무 길다"
    for alias in _ALIAS.findall(text):
        if alias.startswith("p") and not trip.has_place(alias):
            return f"없는 장소 {alias}"
        if alias.startswith("d") and day_index(trip, alias) is None:
            return f"없는 날짜 {alias}"
    if re.search(r"\d", _ALIAS.sub("", text)):
        return "슬롯 밖 숫자"
    if any(phrase in text for phrase in FORBIDDEN_PHRASES):
        return "금지 표현"
    return None


def day_label(trip: Trip, alias: str) -> str:
    i = day_index(trip, alias)
    if i is None:
        raise ValueError(alias)
    head = _ORDINALS[i] if i < len(_ORDINALS) else f"{i + 1}번째"
    return f"{head} 날 ({_WEEKDAYS[trip.days[i].weekday()]})"


def render_thought(trip: Trip, text: str) -> str:
    """검증을 통과한 문장의 슬롯을 실제 이름으로 바꾼다. thought_problem을 먼저 부른다."""
    return _ALIAS.sub(
        lambda m: trip.place(m.group(1)).name if m.group(1).startswith("p") else day_label(trip, m.group(1)),
        text,
    )


# ---- 결과 판정 (명세 11.3) ----

def outcome(best_violations: Sequence[Violation], *, timed_out: bool, checks: int = 0) -> str:
    """checks = 남은 「확인 필요」 수. 위반 모드에서는 위반 속 unknown과 같은 것이라 둘 중 하나만 있어도 확인이 남은 것이다."""
    confirmed, unknown = hard_score(best_violations)
    if confirmed == 0:
        return "solved" if unknown == 0 and checks == 0 else "solved_with_checks"
    return "timeout" if timed_out else "unresolved"

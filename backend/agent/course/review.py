"""다 넣은 일정(review)을 점검하고 덜 건드리는 수부터 고칠 안을 만든다(#1321, 결정 #1237 3~5절). 순수 함수 — DB와 모델을 모른다.

점검(`find_problems`)은 문제를 7종으로 찾는다. 세기는 `HARD_KINDS` 한 곳이 정한다: closed·travel·member는 하드(확정 위반, 의도와 상관없이 늘
낸다), 나머지는 선호다. 하드 판정은 `core.find_violations`를 그대로 쓴다(영업시간을 아는 장소만 — 모르면 「가게에 확인」으로 남는다).

고칠 안(`propose`)은 문제마다 **지금 일정**에서 따로 짠다(카드 하나를 반영해도 다른 카드의 전제가 안 바뀐다). 사다리 ① 날 맞바꾸기 ② 1곳 옮기기
③ 2곳 맞바꾸기를 차례로 시도하고, 그 문제가 풀리고 다른 문제가 늘지 않는 첫 단계에서 멈춘다. 셋 다 안 되면 안 없이 「크게 바꿔야 해요」다.

- 사람이 넣은 일정은 바꾸지 않는다. 여기 나오는 것은 제안뿐이고(`state.locks`도 건드리지 않는다) 반영은 사람이 누른다. 옮기는 장소가 일정에서
  고정 장소여도 되는 이유다 — 고정(locks)은 AI가 코스를 짜며 옮기지 못하게 하는 장치이고, 점검의 안은 사람에게 보이는 제안이다.
- 수는 `reflect`로 적용한다. 반영 화면(FE)이 하는 방식 그대로다: 옮겨 간 장소는 그 날에 남는 장소 뒤에 원래 일정의 순서(날짜 → 그날 순서)대로
  붙고, 그날 순서는 고치지 않는다. `core.apply_move`의 자리 계산(best_position)을 쓰면 반영한 결과와 점검한 결과가 달라진다.
- 모델의 몫(선호 문제의 순서, 고칠 가치, 안이 여럿일 때의 절충)은 `order`·`worth` 훅이다. 비워 두면 코드 기본(입력 순서, 모두 고침)이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, Mapping, Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.constants import MEALS_PER_DAY_MAX

HARD_KINDS = ("closed", "travel", "member")
SOFT_KINDS = ("condition", "goal", "cluster", "meal")
CHECKED_KINDS = (*HARD_KINDS, *SOFT_KINDS)         # 문제가 없을 때 「괜찮아요」로 낼 수 있는 종류(CourseChecked.kind)

BIG_CHANGE = "BIG_CHANGE"      # 사다리 ①~③으로 풀리지 않는다 → 「크게 바꿔야 해요」
NOT_WORTH = "NOT_WORTH"        # 풀 수는 있지만 고치지 않기로 했다(worth 훅이 낸 이유 코드의 기본값)


@dataclass(frozen=True)
class Problem:
    kind: str
    key: tuple                                   # 같은 문제인지 가르는 값. 날짜 위치로 센다 — 날 맞바꾸기로 문제가 다른 날로 옮겨 가면 풀린 것이 아니다
    day: Optional[str] = None                    # 날짜 별칭(하루에 걸린 문제)
    places: tuple[str, ...] = ()
    goal_id: Optional[str] = None                # condition·goal
    variant: Optional[str] = None                # meal: none(식당 없는 날) · many(하루 상한 넘음)

    @property
    def strength(self) -> str:
        return "hard" if self.kind in HARD_KINDS else "soft"


@dataclass(frozen=True)
class Move:
    place: str
    from_day: int                                # 일정의 날짜 위치(0부터)
    to_day: int


@dataclass(frozen=True)
class Attempt:
    step: int                                    # 1 날 맞바꾸기 · 2 1곳 옮기기 · 3 2곳 맞바꾸기
    ok: bool


@dataclass(frozen=True)
class Fix:
    problem: Problem
    step: Optional[int]                          # 안을 찾은 단계. 안이 없으면 None
    moves: tuple[Move, ...] = ()
    remaining: tuple[Problem, ...] = ()          # 안을 따라도 남는 문제(안이 없으면 비어 있다)
    not_fixed: Optional[str] = None              # BIG_CHANGE · worth 훅의 이유 코드
    attempts: tuple[Attempt, ...] = ()

    @property
    def moved(self) -> int:
        return len(self.moves)


@dataclass(frozen=True)
class ReviewResult:
    problems: tuple[Problem, ...]
    fixes: tuple[Fix, ...]                       # problems와 같은 순서(하드 먼저)
    checked: tuple[str, ...]                     # 점검했고 문제가 없는 종류(CHECKED_KINDS 순서). 대상이 없는 종류(목표 없음, 구성원 제약 없음)는 뺀다


# ---------------------------------------------------------------- 점검

def _meal_cap(trip: core.Trip) -> int:
    return -(-len(trip.places) // len(trip.days))


def find_problems(
    trip: core.Trip, course: core.Course, hours: core.Hours, goals: Sequence[goals_mod.Goal] = (),
) -> tuple[Problem, ...]:
    """하드 → 선호 순서. 같은 입력이면 같은 출력이다."""
    grouped: dict[tuple, list] = {}
    for v in core.find_violations(trip, course, hours):
        if v.status != "confirmed":
            continue
        key = ("closed", v.places[0]) if v.kind == "closed" else (v.kind, v.day)
        entry = grouped.setdefault(key, [v.kind, v.day, []])
        entry[2].extend(p for p in v.places if p not in entry[2])
    hard = [Problem(kind, key, day, tuple(places)) for key, (kind, day, places) in grouped.items()]
    hard.sort(key=lambda p: HARD_KINDS.index(p.kind))

    soft: list[Problem] = []
    for r in goals_mod.evaluate_all(trip, course, goals):
        if r.met is False:                                         # 판단할 수 없는 목표(None)는 문제로 세지 않는다
            kind = "goal" if r.goal.origin == "request" else "condition"
            soft.append(Problem(kind, (kind, r.goal.id), r.goal.day, r.goal.places, r.goal.id))
    soft.sort(key=lambda p: SOFT_KINDS.index(p.kind))

    cap = _meal_cap(trip)
    for cluster in core.clusters(trip):
        aliases = tuple(sorted(p.alias for p in cluster))
        if 2 <= len(aliases) <= cap and len({core.locate(course, a)[0] for a in aliases}) > 1:    # 하루에 못 들어가는 큰 묶음은 갈라져도 문제가 아니다
            soft.append(Problem("cluster", ("cluster", aliases), None, aliases))
    counts = core.day_meal_counts(trip, course)
    less = set(core.meal_less_days(trip, course)) if core.meal_cover(trip, course) > 0 else set()
    for i, n in enumerate(counts):
        if n > MEALS_PER_DAY_MAX or i in less:
            soft.append(Problem("meal", ("meal", core.day_alias(i)), core.day_alias(i), variant="many" if n > MEALS_PER_DAY_MAX else "none"))
    return tuple(hard + soft)


def _applicable_kinds(trip: core.Trip, goals: Sequence[goals_mod.Goal]) -> tuple[str, ...]:
    """대상이 있는 점검 종류 — 구성원 제약이 없으면 member, 그 출처의 목표가 없으면 goal·condition은 「괜찮아요」를 낼 수 없다."""
    origins = {g.origin for g in goals}
    return tuple(
        k for k in CHECKED_KINDS
        if not (k == "member" and not trip.member_constraints)
        and not (k == "goal" and "request" not in origins) and not (k == "condition" and "map" not in origins)
    )


# ---------------------------------------------------------------- 수 적용 (반영 화면과 같은 방식)

def reflect(course: core.Course, moves: Mapping[str, int]) -> core.Course:
    """장소 → 옮겨 갈 날 위치. 옮겨 간 장소는 그 날에 남는 장소 뒤에 원래 일정의 순서대로 붙는다. 그날 순서는 따로 고치지 않는다."""
    days = [[p for p in day if p not in moves] for day in course]
    for p in sorted(moves, key=lambda q: core.locate(course, q)):
        days[moves[p]].append(p)
    return tuple(tuple(d) for d in days)


def _candidates(course: core.Course, step: int, movable: Optional[Collection[str]] = None):
    n = len(course)
    free = (lambda p: True) if movable is None else movable.__contains__
    if step == 1:
        for i in range(n):
            for j in range(i + 1, n):
                if course[i] or course[j]:
                    yield {**{p: j for p in course[i]}, **{p: i for p in course[j]}}
    elif step == 2:
        for i, day in enumerate(course):
            for p in filter(free, day):
                for t in range(n):
                    if t != i:
                        yield {p: t}
    else:
        placed = [(p, i) for i, day in enumerate(course) for p in day if free(p)]
        for x, (a, da) in enumerate(placed):
            for b, db in placed[x + 1:]:
                if da != db:
                    yield {a: db, b: da}


def propose(
    trip: core.Trip, course: core.Course, hours: core.Hours, goals: Sequence[goals_mod.Goal], problem: Problem,
    before: Optional[Sequence[Problem]] = None, movable: Optional[Collection[str]] = None,
) -> Fix:
    """이 문제 하나를 고치는 가장 덜 건드리는 안. 문제가 풀리고 이 일정에 없던 문제가 새로 생기지 않는 첫 단계에서 멈춘다.
    같은 단계에서 안이 여럿이면 (남는 하드 문제 수, 남는 문제 수, 이동 합계, 만든 순서)가 가장 작은 것."""
    before_keys = {p.key for p in (before if before is not None else find_problems(trip, course, hours, goals))}
    attempts: list[Attempt] = []
    for step in (1, 2, 3):
        best = None
        for order, moves in enumerate(_candidates(course, step, movable)):
            after_course = reflect(course, moves)
            after = find_problems(trip, after_course, hours, goals)
            keys = {p.key for p in after}
            if problem.key in keys or not keys <= before_keys:
                continue
            rank = (sum(p.strength == "hard" for p in after), len(after), core.course_travel(trip, after_course), order)
            if best is None or rank < best[0]:
                best = (rank, moves, after)
        attempts.append(Attempt(step, best is not None))
        if best is not None:
            _, moves, after = best
            made = tuple(Move(p, core.locate(course, p)[0], to) for p, to in sorted(moves.items(), key=lambda kv: core.locate(course, kv[0])))
            return Fix(problem, step, made, tuple(after), None, tuple(attempts))
    return Fix(problem, None, (), (), BIG_CHANGE, tuple(attempts))


def review(
    trip: core.Trip, course: core.Course, hours: core.Hours, goals: Sequence[goals_mod.Goal] = (), *,
    order: Optional[Callable[[Sequence[Problem]], Sequence[Problem]]] = None,
    worth: Optional[Callable[[Problem, Fix], Optional[str]]] = None, movable: Optional[Collection[str]] = None,
) -> ReviewResult:
    """지금 일정(course: 날짜 위치별 장소, 사람이 정한 순서 그대로)을 점검하고 문제마다 고칠 안을 만든다. 일정은 바꾸지 않는다.
    하드 문제는 늘 먼저, 그 안에서도 늘 안(또는 「크게 바꿔야 해요」)이 나온다 — worth 훅은 하드 문제의 안을 지우지 못한다.
    movable이 있으면 ②③은 그 장소만 옮긴다(① 날 맞바꾸기는 날 전체라 늘 가능). 남은 곳 채우기(fill)가 AI가 둔 미배정 장소를 따로 옮기지 않게 한다."""
    problems = find_problems(trip, course, hours, goals)
    hard = [p for p in problems if p.strength == "hard"]
    soft = [p for p in problems if p.strength == "soft"]
    if order is not None:
        ranked = list(order(soft))
        soft = ranked + [p for p in soft if p not in ranked]       # 훅이 빠뜨린 문제도 남는다
    fixes = []
    for p in (*hard, *soft):
        fix = propose(trip, course, hours, goals, p, problems, movable)
        reason = worth(p, fix) if worth is not None and fix.step is not None and p.strength == "soft" else None
        fixes.append(Fix(p, None, (), (), reason, fix.attempts) if reason else fix)
    found = {p.kind for p in problems}
    checked = tuple(k for k in _applicable_kinds(trip, goals) if k not in found)
    return ReviewResult(tuple((*hard, *soft)), tuple(fixes), checked)

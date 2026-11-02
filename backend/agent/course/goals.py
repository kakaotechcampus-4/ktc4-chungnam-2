"""요청 목표(명세 8.2) — 점수와 매개변수 검증. 순수 함수만 둔다. 점수는 코드가 계산하고 모델은 목표 종류와 별칭만 고른다.

목표 7종: day_indoor, night_end, daily_walk_low, day_light, place_on_day, together, day_has(그날 코스에 tag 라벨이 참인 장소가 있다).
라벨이 비어 있는 장소는 "라벨을 모른다"로 보고 그 목표 점수에서 뺀다(지어내지 않는다). 판단할 대상이 하나도 없으면
충족 여부는 None(판단할 수 없음)이고 충족 수·간격 합계에서 빠진다.

충족 여부(met)는 코드의 임계값이다: 실내 비율 ≥ INDOOR_MET_RATIO, 하루 도보 최대 ≤ DAILY_WALK_LOW_MAX_MIN, 하루 장소 수 ≤ 평균−1.
간격(gap)은 못 미친 정도를 0~1로 나눈 값이다 — 한 수씩 올리는 규칙이 "충족 직전까지 좋아지는 수"를 알아보게 한다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from agent.course import core
from agent.course.constants import (
    DAILY_WALK_LOW_MAX_MIN, DAY_HAS_CATEGORY_TAGS, DAY_HAS_TAGS, GOALS_MAX, INDOOR_LABEL, INDOOR_MET_RATIO, NIGHT_LABEL,
)
from agent.course.core import Course, Trip
from agent.course.korean import attach

GoalKind = Literal["day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together", "day_has"]
GOAL_KINDS: tuple[str, ...] = ("day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together", "day_has")


@dataclass(frozen=True)
class Goal:
    kind: str
    day: Optional[str] = None            # d1 …
    places: tuple[str, ...] = ()         # p1 …
    tag: Optional[str] = None            # day_has만: DAY_HAS_TAGS의 키

    @property
    def id(self) -> str:
        return ":".join([self.kind, *([self.day] if self.day else []), *(["+".join(self.places)] if self.places else []),
                         *([self.tag] if self.tag else [])])


@dataclass(frozen=True)
class GoalResult:
    goal: Goal
    met: Optional[bool]                  # None = 판단할 수 없다(라벨을 아는 장소가 없다)
    gap: float                           # 0이면 충족. 판단할 수 없으면 0
    value: Optional[float]               # 원래 점수(비율·분·장소 수·1/0). 판단할 수 없으면 None


def normalize(
    trip: Trip, kind: str, day: Optional[str], places: Sequence[str], tag: Optional[str] = None,
) -> tuple[Optional[Goal], Optional[str]]:
    """매개변수를 검사해 Goal을 만든다. 안 되면 (None, 이유). 종류에 필요 없는 매개변수는 버린다."""
    if kind not in GOAL_KINDS:
        return None, f"모르는 목표 종류 {kind}"
    if kind == "day_has" and tag not in DAY_HAS_TAGS and tag not in DAY_HAS_CATEGORY_TAGS:
        return None, f"day_has에는 허용된 tag가 필요하다({tag})"
    needs_day = kind in ("day_indoor", "night_end", "day_light", "place_on_day", "day_has")
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
    return Goal(kind, day if needs_day else None, chosen, tag if kind == "day_has" else None), None


def tag_noun(tag: Optional[str]) -> str:
    """day_has의 tag를 화면에 쓰는 말로. 라벨 종류와 카테고리 종류가 같은 자리에서 나온다."""
    return (DAY_HAS_TAGS.get(tag or "") or DAY_HAS_CATEGORY_TAGS[tag or ""])[1]


def tag_hit(trip: Trip, place: str, tag: Optional[str]) -> bool:
    """그 장소가 day_has tag에 든다. 카테고리 종류는 핀의 카테고리로, 라벨 종류는 Place.labels로 본다."""
    if tag in DAY_HAS_CATEGORY_TAGS:
        return trip.place(place).category == DAY_HAS_CATEGORY_TAGS[tag][0]
    return DAY_HAS_TAGS[tag or ""][0] in trip.place(place).labels


def _known(trip: Trip, place: str) -> bool:
    return bool(trip.place(place).labels)


def day_light_cap(trip: Trip) -> int:
    return max(1, len(trip.places) // len(trip.days) - 1)


def day_min_places(trip: Trip) -> int:
    """날짜 균형의 하한(#1008 K2). 한 날이 이보다 적으면 목표를 채우려고 그날 장소를 다른 날로 뺀 것으로 보고 지킨 것으로 세지 않는다.
    상한(day_light_cap)과 같은 값이라 여유 목표와 한 코스에서 함께 지키려면 날짜가 고르게 나뉘어야 한다."""
    return day_light_cap(trip)


def evaluate(trip: Trip, course: Course, goal: Goal) -> GoalResult:
    unknown = GoalResult(goal, None, 0.0, None)
    if goal.kind == "day_has":
        i = core.day_index(trip, goal.day or "")
        day = course[i] if i is not None else ()
        if any(tag_hit(trip, p, goal.tag) for p in day):
            return GoalResult(goal, True, 0.0, 1.0)
        if goal.tag not in DAY_HAS_CATEGORY_TAGS and day and not any(_known(trip, p) for p in day):
            return unknown                                   # 그날 장소의 라벨을 하나도 몰라 없다고 말할 수 없다
        return GoalResult(goal, False, 1.0, 0.0)
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
            floor = day_min_places(trip)
            thin = max(0, floor - len(day)) / floor              # 그날 장소를 빼서 비율을 채운 코스는 지킨 것이 아니다
            return GoalResult(goal, ratio >= INDOOR_MET_RATIO and thin == 0, max(0.0, INDOOR_MET_RATIO - ratio) + thin, ratio)
        if not _known(trip, day[-1]):
            return unknown
        hit = NIGHT_LABEL in trip.place(day[-1]).labels
        return GoalResult(goal, hit, 0.0 if hit else 1.0, 1.0 if hit else 0.0)
    if goal.kind == "daily_walk_low":
        worst = max((core.day_walk(trip, d) for d in course), default=0)
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


_PIECE_SPLIT = re.compile(r"[,.;!?·\n]|그리고")
_FILLER = re.compile(r"감사합니다|감사해요|고맙습니다|고마워요|안녕하세요|잘 ?부탁(?:드립니다|드려요|해요)|해\s?주세요|해줘요?|부탁(?:해요|드려요|드립니다)?|짜\s?주세요|짜줘요?|싶어요|싶고|싶다|했으면|좋겠어요|좋겠고|코스|일정|여행|그리고|또|저는|우리는|이번|으로|에서|에는|에도|까지|부터|[은는이가을를에도와과로의]")


def leftover_pieces(request_text: str, covered: Sequence[str]) -> list[str]:
    """요청에서 목표 quote와 unmatched 어디에도 쓰이지 않은 조각(#1008 K1). 모델이 한 문장의 일부를 말없이 버려도 사용자가 알 수 있게
    unmatched로 남긴다. 덮인 글자를 지우고 남은 글을 구두점·접속어로 나눠, 군말(요청 문구, 조사)을 뺀 뒤 한글이 3자 이상 남는 조각만 쓴다.
    원문 부분 문자열이라 화면에 그대로 쓸 수 있다."""
    mask = [False] * len(request_text)
    for piece in covered:
        start = request_text.find(piece) if piece.strip() else -1
        while start != -1:
            for i in range(start, start + len(piece)):
                mask[i] = True
            start = request_text.find(piece, start + len(piece))
    rest = "".join("\n" if m else c for c, m in zip(request_text, mask))
    out: list[str] = []
    for part in _PIECE_SPLIT.split(rest):
        piece = part.strip()
        if len(re.findall(r"[가-힣]", _FILLER.sub("", piece))) >= 3 and piece in request_text:
            out.append(piece)
    return out


# ---- 목표로 바꾸지 않는 요청 조각 (#1128) ----
# 코드가 조각의 종류를 보고 고정 문장을 고른다(모델이 이유를 쓰지 않는다). 조각 원문은 문장에 섞지 않고 unmatched 조각으로 둔다(#717).
_DELEGATE_RE = re.compile(r"알아서|맡길|맡겨|마음대로|적당히|아무렇게나|아무거나")
_DELEGATE_FILLER = re.compile(r"그냥|대충|좀|잘|짜|해|줘|주세요|요")
_REST_DAY_RE = re.compile(r"아무것도\s?(?:안|하지|없)|아무\s?데도|쉴래|쉬고\s?싶|쉬려|푹\s?쉬|쉬는\s?날로|비워|비우|비울")
_TIME_RE = re.compile(r"(?<![0-9])[0-9]{1,2}\s?시(?![간장작])|[0-9]{1,2}:[0-9]{2}"
                      r"|(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|열한|열두|몇)\s?시(?![간장작])|오전|오후")
# 한 단어만으로는 뜻이 갈리는 말: 「경복궁 예약했어」는 시간 지정이 아니고 「카페에서 휴식」은 하루 비우기가 아니다 — 시각·날짜 말과 같이 있을 때만 본다
_RESERVE_RE = re.compile(r"예약")
_DAYPART_RE = re.compile(r"아침|점심|저녁|오전|오후|밤")
_REST_RE = re.compile(r"휴식")
_DAY_WORD_RE = re.compile(r"[월화수목금토일]요일|첫날|첫째|둘째|셋째|넷째|다섯째|마지막\s?날|[0-9]+\s?일(?:째|차)?(?![가-힣])|하루|그날")
_DAILY_RE = re.compile(r"매일|날마다|모든\s?날|하루에\s?(?:한|하나)|하루\s?(?:한|하나)씩")
REST_DAY, TIME_GIVEN = "REST_DAY", "TIME_GIVEN"
PIECE_REASONS = {
    REST_DAY: "확정 장소를 모든 날에 나눠요. 하루를 비우려면 장소를 줄여 주세요.",
    TIME_GIVEN: "시간은 정하지 않아요. 코스는 날짜별 순서와 이동만 짜요.",
}


def is_delegation(piece: str) -> bool:
    """「알아서 잘 짜줘」처럼 맡기는 말뿐인 조각. 목표도 unmatched도 아니다 — 빈 요청과 같이 기본 기준으로 짠다.
    맡기는 말을 빼고도 한글이 3자 이상 남으면(「알아서 카페 넣어줘」) 맡김이 아니다."""
    if not _DELEGATE_RE.search(piece):
        return False
    rest = _DELEGATE_FILLER.sub("", _FILLER.sub("", _DELEGATE_RE.sub("", piece)))
    return len(re.findall(r"[가-힣]", rest)) < 3


def piece_reason(piece: str) -> Optional[str]:
    """unmatched 조각을 목표로 바꾸지 않는 이유(PIECE_REASONS 키). 하루 비우기를 시간보다 먼저 본다. 모르면 None(판단할 수 없음)."""
    if _REST_DAY_RE.search(piece) or (_REST_RE.search(piece) and _DAY_WORD_RE.search(piece)):
        return REST_DAY
    if _TIME_RE.search(piece) or (_RESERVE_RE.search(piece) and _DAYPART_RE.search(piece)):
        return TIME_GIVEN
    return None


def _daily(trip: Trip, g) -> list[tuple[Optional[Goal], Optional[str]]]:
    """「카페는 매일 하나씩」 — 날짜 없는 day_has의 quote가 모든 날을 말하면 날마다 day_has 하나씩(#1128). 아니면 빈 목록."""
    if g.kind != "day_has" or g.day is not None or not _DAILY_RE.search(g.quote):
        return []
    return [normalize(trip, g.kind, core.day_alias(i), g.places, getattr(g, "tag", None)) for i in range(len(trip.days))]


def unlisted_mentions(trip: Trip, request_text: str, goals: Sequence[Goal], quotes: Sequence[str]) -> list[str]:
    """목표 quote 안에 코스 장소의 이름이 있는데 그 장소가 어떤 목표의 places에도 없으면, 그 장소를 말한 조각(#1008 K1).
    「마지막 날 밤에 N서울타워」 전체를 quote로 쓰고 야경 목표 하나만 내면 장소 요청이 말없이 사라지기 때문이다."""
    used = {p for g in goals for p in g.places}
    out: list[str] = []
    for place in trip.places:
        if place.alias in used or len(place.name) < 2:
            continue
        if any(place.name in q for q in quotes):
            clause = next((c.strip() for c in _PIECE_SPLIT.split(request_text) if place.name in c), "")
            if clause and clause in request_text:
                out.append(clause)
    return out


def verify_goal_set(trip: Trip, request_text: str, goal_set) -> VerifiedGoals:
    """모델이 낸 목표(CourseGoalSet)를 코드가 검증한다: 종류별 매개변수, 별칭, quote가 요청 원문의 부분 문자열인지.
    떨어진 목표는 버리고, 그 quote가 원문 조각이면 unmatched로 옮긴다. unmatched도 원문 부분 문자열만 남긴다.
    날마다 나눈 day_has(「매일」)는 다른 목표 뒤에 붙여 GOALS_MAX를 넘으면 그쪽이 먼저 빠진다. 맡기는 말뿐인 조각은 unmatched에서 뺀다."""
    goals: list[Goal] = []
    daily: list[Goal] = []
    dropped: list[str] = []
    unmatched: list[str] = []
    for g in goal_set.goals:
        problem = None
        if g.source != "request":
            problem = "요청이 아닌 근거"
        elif not g.quote.strip() or g.quote not in request_text:
            problem = "quote가 원문에 없다"
        made = (_daily(trip, g) or [normalize(trip, g.kind, g.day, g.places, getattr(g, "tag", None))]) if problem is None else [(None, problem)]
        if any(goal is None for goal, _ in made):
            dropped += [f"{g.kind}: {why}" for goal, why in made if goal is None][:1]
            if g.quote.strip() and g.quote in request_text:
                unmatched.append(g.quote)
        else:
            (daily if len(made) > 1 else goals).extend(goal for goal, _ in made if goal is not None)
    unmatched += [u for u in goal_set.unmatched if u.strip() and u in request_text]
    quotes = [g.quote for g in goal_set.goals if g.quote.strip() and g.quote in request_text]
    unmatched += unlisted_mentions(trip, request_text, goals + daily, quotes)
    unmatched += leftover_pieces(request_text, quotes + unmatched)
    kept = [u for u in dict.fromkeys(unmatched) if not is_delegation(u)]
    return VerifiedGoals(truncate(goals + daily), tuple(kept), tuple(dropped))


def label(trip: Trip, goal: Goal) -> str:
    """화면 문장 조각(코드 템플릿). 장소 이름은 화면에서만 쓴다."""
    day = core.day_label(trip, goal.day) if goal.day else ""
    names = [trip.place(p).name for p in goal.places]
    return {
        "day_indoor": f"{day}은 실내 위주로",
        "night_end": f"{day} 마지막은 야경 명소",
        "daily_walk_low": "하루 걷는 시간 줄이기",
        "day_light": f"{day}은 여유 있게",
        "place_on_day": f"{attach(names[0], '을/를')} {day}에" if goal.kind == "place_on_day" else "",
        "together": f"{', '.join(names)} 같은 날" if goal.kind == "together" else "",
        "day_has": f"{day}에 {tag_noun(goal.tag)} 장소 넣기" if goal.kind == "day_has" else "",
    }[goal.kind]


# ---- 데이터 확인 (check_goals, pivot 8.2절) ----
# 코스를 짜기 전에 코드가 "이 리스트로 이 목표가 가능한가"를 확인한다. 라벨을 모르는 장소(labels 비어 있음)는 "라벨을 아는 장소 수"에서 뺀다.

NO_NIGHT_PLACE = "NO_NIGHT_PLACE"
NIGHT_PLACE_CLOSED_ON_DAY = "NIGHT_PLACE_CLOSED_ON_DAY"
FEW_INDOOR = "FEW_INDOOR"
PLACE_CLOSED_ON_DAY = "PLACE_CLOSED_ON_DAY"
NO_COMMON_OPEN_DAY = "NO_COMMON_OPEN_DAY"
NO_TAGGED_PLACE = "NO_TAGGED_PLACE"
TAGGED_PLACE_CLOSED_ON_DAY = "TAGGED_PLACE_CLOSED_ON_DAY"
LABELS_UNKNOWN = "LABELS_UNKNOWN"

_CHECK_SENTENCES = {
    NO_NIGHT_PLACE: "야경 명소가 이 리스트에 없어요",
    NIGHT_PLACE_CLOSED_ON_DAY: "야경 명소가 그날 모두 쉬어요",
    FEW_INDOOR: "실내 장소가 적어서 그날을 실내 위주로 채우기 어려워요",
    PLACE_CLOSED_ON_DAY: "그 장소가 그날 쉬어요",
    NO_COMMON_OPEN_DAY: "두 장소가 함께 영업하는 날이 없어요",
    NO_TAGGED_PLACE: "확정 리스트에 그런 장소가 없어요",                    # day_has는 check_sentence가 tag 이름을 넣어 바꾼다
    TAGGED_PLACE_CLOSED_ON_DAY: "그런 장소가 그날 모두 쉬어요",
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
    elif goal.kind == "day_has":
        by_category = goal.tag in DAY_HAS_CATEGORY_TAGS
        tagged = [p.alias for p in trip.places if tag_hit(trip, p.alias, goal.tag)]
        facts = {"tag": goal.tag, "tagged_places": len(tagged), "labeled_places": len(labeled),
                 "tagged_closed_on_day": [p for p in tagged if goal.day in _closed_days(trip, hours, p)]}
        if not labeled and not by_category:
            feasible, reasons = None, [LABELS_UNKNOWN]
        elif not tagged:
            feasible, reasons = False, [NO_TAGGED_PLACE]
        elif len(facts["tagged_closed_on_day"]) == len(tagged):
            feasible, reasons = False, [TAGGED_PLACE_CLOSED_ON_DAY]
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
    head = f"‘{label(trip, goal)}’ 목표는"
    if check["feasible"] is True:
        return f"{head} 가능해 보여요."
    noun = tag_noun(goal.tag) if goal.kind == "day_has" else ""
    sentences = {**_CHECK_SENTENCES, NO_TAGGED_PLACE: f"확정 리스트에 {noun} 장소가 없어요",
                 TAGGED_PLACE_CLOSED_ON_DAY: f"{noun} 장소가 그날 모두 쉬어요"}
    why = ". ".join(sentences[r] for r in check["reasons"]) or "영업 여부를 몰라 확인이 필요해요"
    return f"{head} 어려워 보여요. {why}."


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
        "day_has": (f"{tag_noun(goal.tag)} 있음", f"{tag_noun(goal.tag)} 없음") if goal.kind == "day_has" else ("", ""),
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
    return Goal(goal.kind, day, goal.places, goal.tag)

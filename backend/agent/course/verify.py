"""화면에 나가는 모델 문장이 코드가 아는 사실과 어긋나는지 검사한다(검증이 지휘를 견제). 순수 함수만 둔다.

core.thought_problem은 문장의 *모양*(슬롯 밖 숫자 금지, 금지 표현)을 막는다. 여기서는 문장이 *주장하는 것*을 막는다:
  - 확정 위반이 없다/해결됐다/남았다(종류별: 휴무, 도보), 영업 확인이 끝났다/남았다
  - 요청 목표를 지켰다/못 지켰다(목표별: 야경, 실내, 걷기, 여유, 장소·날짜, 같은 날)
  - 어떤 장소가 어느 날에 쉬어요/열어요/가능해요
  - 숫자 낱말(두 곳, 삼십 분 …)이 코드의 값에 없는 경우 — 숫자 글자는 이미 thought_problem이 막는다
코드가 확인할 수 있는 주장이 틀리면 막는다. 코드가 확인할 수 없는 말(이유, 계획, 감상)은 그대로 둔다 — 보수적으로, 확실히 틀린 것만 막는다.
막히면 모델을 다시 부르지 않고 코드 사실만으로 만든 문장(fact_sentence)으로 바꾼다. 문장 검사는 별칭 슬롯({p4}, {d2})이 든 원문에 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.constants import DAY_TRAVEL_MAX_MIN, LEG_MAX_MIN
from agent.course.korean import attach

SLOT = re.compile(r"\{([pd][1-9][0-9]*)\}")
CLAUSE_SPLIT = re.compile(r"[,.·;!?]|지만|는데|으나|면서|고(?=\s)")

# "없" 뒤에 이런 말이 붙으면 사실 주장이 아니라 의도·질문이다("없도록 다시 짜요", "없는지 볼게요").
_NO = r"없(?!는지|을지|을까|나\b|도록|게|으려|으면|다면|애|앨|어지)"
ZERO_RE = re.compile(_NO + r"|해결(?:됐|되었|돼|했|된)|해소(?:됐|되었|돼|했|된)|풀렸|풀린|사라졌|사라진|고쳤|고친|없앴|없앤")
REMAIN_RE = re.compile(r"남아|남았|남은|있어|있는|있다|있네")
CONDITIONAL_RE = re.compile(r"으면|다면|도록|려고|려면|지 않")
CLOSED_RE = re.compile(r"쉬|휴무|휴관|닫|영업하지 않|열지 않|안 열")
OPEN_RE = re.compile(r"열(?!지)|영업(?!\s?(?:확인|여부))|운영")
NEGATED_RE = re.compile(r"^.{0,4}(?:지 않|지 못|않|못)")
FEASIBLE_RE = re.compile(r"가능")
# 모델은 "확정 위반"을 "확정 조건", "확정 관련 문제"처럼도 쓴다(입력의 hard.confirmed). 같은 주장으로 본다.
VIOLATION_TOPIC_RE = re.compile(r"위반|문제|확정\s?(?:조건|관련|위반|문제|오류|사항)")
HARD_OK_RE = re.compile(r"통과|충족|만족")
ALL_CLEAR_RE = re.compile(r"(?:점검|검사|검증)(?:을|도|은|는)?\s?통과")
CHECK_TOPIC_RE = re.compile(r"영업 확인|확인 필요|영업 여부|휴무 확인")
CHECK_DONE_RE = re.compile(r"통과|완료|마쳤|끝났|" + _NO)
CHECK_LEFT_RE = re.compile(r"남|있")
KEEP_RE = re.compile(r"지켰|지킨|지켜졌|지켜요|지켜서|지키며|지키고|충족|달성|이뤘|이룬|만족했|반영됐|반영되었|반영했")
GAVE_UP_RE = re.compile(r"못 ?(?:지켰|지켜|지킨|이뤘|이루|충족|달성)|지키지 (?:못|않)|지켜지지 (?:못|않)|충족하지|달성하지|미달|이루지 못|반영하지 못|어긋")
NOT_A_GOAL_RE = re.compile(r"상한|한도|제한|확정")
TOPICS = {
    "night_end": re.compile(r"야경"),
    "day_indoor": re.compile(r"실내"),
    "daily_walk_low": re.compile(r"걷|걸|도보|이동"),
    "day_light": re.compile(r"여유|빽빽|느긋"),
}
GOAL_WORD_RE = re.compile(r"목표|요청")
PLACEMENT_RE = re.compile(r"배치|배정|날짜|방문")


@dataclass(frozen=True)
class Reference:
    """문장을 견주는 코드 사실: 모델이 본(또는 고른) 후보의 코스와 위반, 지금 아는 영업시간, 요청 목표."""
    trip: core.Trip
    hours: core.Hours
    course: core.Course
    violations: tuple[core.Violation, ...]
    goals: tuple[goals_mod.Goal, ...]
    subject: str = "후보"                   # 후보가 아직 없으면(첫 optimize 전) "초안"
    candidate_count: int = 0

    @property
    def confirmed(self) -> list[core.Violation]:
        return [v for v in self.violations if v.status == "confirmed"]

    @property
    def checks(self) -> tuple[core.Violation, ...]:
        return core.find_checks(self.trip, self.course, self.hours)

    @property
    def goal_results(self) -> tuple[goals_mod.GoalResult, ...]:
        return goals_mod.evaluate_all(self.trip, self.course, self.goals)

    def day_of(self, place: str) -> Optional[str]:
        return next((core.day_alias(i) for i, day in enumerate(self.course) if place in day), None)

    def status(self, place: str, day: str) -> core.DayStatus:
        i = core.day_index(self.trip, day)
        return "unknown" if i is None else core.status_on(self.hours, place, self.trip.days[i])


# ---- 문장 검사 ----

def problems(ref: Reference, text: str) -> list[str]:
    """text(슬롯이 든 모델 원문)가 코드 사실과 어긋나는 점들(화면에 보일 한국어 이유). 없으면 빈 목록."""
    out: list[str] = []
    for clause in CLAUSE_SPLIT.split(text):
        if not clause.strip():
            continue
        out += _violation_claims(ref, clause)
        out += _check_claims(ref, clause)
        out += _goal_claims(ref, clause)
        out += _closed_day_claims(ref, text, clause)
    out += _number_claims(ref, text)
    return list(dict.fromkeys(out))


def _scope(ref: Reference, clause: str) -> tuple[str, list[core.Violation]]:
    """절이 말하는 위반의 종류(휴무/도보)에 맞는 확정 위반만."""
    closed, travel = bool(re.search(r"휴무|쉬는|휴관", clause)), bool(re.search(r"도보|걷|이동|구간", clause))
    if closed and not travel:
        return "휴무 ", [v for v in ref.confirmed if v.kind == "closed"]
    if travel and not closed:
        return "도보 ", [v for v in ref.confirmed if v.kind in ("travel", "member")]
    return "", ref.confirmed


def _violation_claims(ref: Reference, clause: str) -> list[str]:
    if ALL_CLEAR_RE.search(clause) and not CONDITIONAL_RE.search(clause):       # "점검도 통과한 후보" — 위반도 확인 필요도 없다는 말이다
        left = ([f"확정 위반 {len(ref.confirmed)}개"] if ref.confirmed else []) + ([f"영업 확인이 필요한 곳 {len(ref.checks)}곳"] if ref.checks else [])
        return [f"점검을 통과했다고 썼지만 결과에는 남은 것이 있어요({' · '.join(left)})"] if left else []
    if not VIOLATION_TOPIC_RE.search(clause):
        return []
    word, scoped = _scope(ref, clause)
    zero = ZERO_RE.search(clause) or ((HARD_OK_RE.search(clause) or KEEP_RE.search(clause)) if "확정" in clause else None)
    if zero and not CONDITIONAL_RE.search(clause[:zero.start()]):
        if scoped:
            return [f"{word}확정 위반이 없다고 썼지만 결과에는 {len(scoped)}개가 남아 있어요"]
        return []
    if "위반" in clause and REMAIN_RE.search(clause) and not CONDITIONAL_RE.search(clause) and not scoped:
        return [f"{word}확정 위반이 남았다고 썼지만 결과에는 없어요"]
    return []


def _check_claims(ref: Reference, clause: str) -> list[str]:
    if not CHECK_TOPIC_RE.search(clause):
        return []
    places = [m.group(1) for m in SLOT.finditer(clause) if m.group(1).startswith("p") and ref.trip.has_place(m.group(1))]
    if places:
        unsure = [p for p in places if (d := ref.day_of(p)) is not None and ref.status(p, d) != "open"]
        count_text = f"{len(unsure)}곳" if unsure else "0곳"
    else:
        unsure, count_text = list(ref.checks), f"{len(ref.checks)}곳"
    if CHECK_DONE_RE.search(clause) and unsure:
        return [f"영업 확인이 끝났다고 썼지만 확인이 필요한 곳이 {count_text} 남아 있어요"]
    if not CHECK_DONE_RE.search(clause) and CHECK_LEFT_RE.search(clause) and not CONDITIONAL_RE.search(clause) and not unsure:
        return ["영업 확인이 남았다고 썼지만 확인이 필요한 곳이 없어요"]
    return []


def _goal_claims(ref: Reference, clause: str) -> list[str]:
    if not ref.goals or NOT_A_GOAL_RE.search(clause):
        return []
    claim = "gave_up" if GAVE_UP_RE.search(clause) else "keep" if KEEP_RE.search(clause) else None
    if claim is None or (claim == "keep" and CONDITIONAL_RE.search(clause) and "않" in clause):
        return []
    slots = [m.group(1) for m in SLOT.finditer(clause)]
    results = ref.goal_results
    matched = [r for r in results if _on_topic(r.goal, clause, slots)]
    any_topic = any(rx.search(clause) for rx in TOPICS.values())
    if not matched:
        if any_topic or not GOAL_WORD_RE.search(clause):
            return []                                    # 코드가 이 말에 맞는 목표를 모른다 — 확인할 수 없는 말은 둔다
        matched = list(results)
    names = ", ".join(goals_mod.label(ref.trip, r.goal) for r in matched)
    if claim == "keep" and any(r.met is not True for r in matched):
        bad = ", ".join(goals_mod.label(ref.trip, r.goal) for r in matched if r.met is not True)
        return [f"{names}를 지켰다고 썼지만 결과에서는 못 지킨 목표가 있어요({bad})"]
    if claim == "gave_up" and all(r.met is True for r in matched):
        return [f"{names}를 못 지켰다고 썼지만 결과에서는 지켰어요"]
    return []


def _on_topic(goal: goals_mod.Goal, clause: str, slots: Sequence[str]) -> bool:
    if goal.kind in TOPICS:
        return bool(TOPICS[goal.kind].search(clause))
    if goal.kind == "place_on_day":
        return goal.places[0] in slots or (goal.day in slots and bool(PLACEMENT_RE.search(clause)))
    return all(p in slots for p in goal.places) or "같은 날" in clause         # together


def _closed_day_claims(ref: Reference, text: str, clause: str) -> list[str]:
    all_slots = [(m.start(), m.group(1)) for m in SLOT.finditer(text)]
    all_places = [s for _, s in all_slots if s.startswith("p") and ref.trip.has_place(s)]
    all_days = [s for _, s in all_slots if s.startswith("d") and core.day_index(ref.trip, s) is not None]
    slots = [(m.start(), m.group(1)) for m in SLOT.finditer(clause)]
    out: list[str] = []
    for rx, kind in ((CLOSED_RE, "closed"), (OPEN_RE, "open"), (FEASIBLE_RE, "feasible")):
        m = rx.search(clause)
        if m is None:
            continue
        before = [s for pos, s in slots if pos < m.start()]
        day = next((s for s in reversed(before) if s.startswith("d")), all_days[0] if len(set(all_days)) == 1 else None)
        place = next((s for s in reversed(before) if s.startswith("p")), all_places[0] if len(set(all_places)) == 1 else None)
        if day is None or place is None or core.day_index(ref.trip, day) is None or not ref.trip.has_place(place):
            continue
        status = ref.status(place, day)
        negated = bool(NEGATED_RE.match(clause[m.end():])) and kind != "feasible"
        says_closed = (kind == "closed") != negated
        name = attach(ref.trip.place(place).name, "이/가")
        when = core.day_label(ref.trip, day)
        if kind == "feasible":
            if status == "closed":
                out.append(f"{name} {when}에 가능하다고 썼지만 그날 쉬어요")
        elif says_closed and status != "closed":
            out.append(f"{name} {when}에 쉰다고 썼지만 결과에서는 {'영업 여부를 몰라요' if status == 'unknown' else '여는 날이에요'}")
        elif not says_closed and status != "open":
            out.append(f"{name} {when}에 연다고 썼지만 결과에서는 {'쉬는 날이에요' if status == 'closed' else '영업 여부를 몰라요'}")
    return out


# 숫자 낱말: 숫자 글자(0-9)는 core.thought_problem이 막지만 "두 곳", "삼십 분"은 글자 검사를 피한다. 코드의 값에 없으면 막는다.
_NATIVE = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "열한": 11, "열두": 12, "스무": 20}
_SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_NATIVE_WORDS = "|".join(sorted(_NATIVE, key=len, reverse=True))
_SINO_WORD = r"(?:[일이삼사오육칠팔구]?백)?(?:[일이삼사오육칠팔구]?십)(?:[일이삼사오육칠팔구])?|[일이삼사오육칠팔구]?백(?:[일이삼사오육칠팔구])?"
NUMBER_RE = re.compile(rf"(?<![가-힣])({_NATIVE_WORDS}|{_SINO_WORD})\s?(분|시간|곳|개|명|건)")


def _sino_value(word: str) -> int:
    total, rest = 0, word
    if "백" in rest:
        head, rest = rest.split("백", 1)
        total += 100 * (_SINO[head] if head else 1)
    if "십" in rest:
        head, rest = rest.split("십", 1)
        total += 10 * (_SINO[head] if head else 1)
    return total + (_SINO[rest] if rest else 0)


def _fact_numbers(ref: Reference) -> set[int]:
    trip = ref.trip
    days = [core.day_travel(trip, d) for d in ref.course]
    nums = {len(ref.confirmed), len(ref.violations) - len(ref.confirmed), len(ref.checks), len(trip.places), len(trip.days), len(ref.goals),
            ref.candidate_count, LEG_MAX_MIN, DAY_TRAVEL_MAX_MIN, sum(days), max(days, default=0), *days, *(len(d) for d in ref.course)}
    for v in ref.violations:
        nums |= {int(x) for x in v.detail.values()}
    return nums


def _number_claims(ref: Reference, text: str) -> list[str]:
    stripped = SLOT.sub(" ", text)
    allowed = _fact_numbers(ref)
    out = []
    for m in NUMBER_RE.finditer(stripped):
        word, unit = m.group(1), m.group(2)
        value = _NATIVE[word] if word in _NATIVE else _sino_value(word)
        minutes = value * 60 if unit == "시간" else value
        if value not in allowed and minutes not in allowed:
            out.append(f"「{m.group(0)}」라는 수가 결과에 없어요")
    return out


# ---- 코드 문장 (모델 문장이 막혔을 때) ----

def _violation_text(trip: core.Trip, v: core.Violation) -> str:
    when = core.day_label(trip, v.day)
    if v.kind == "closed":
        return f"{attach(trip.place(v.places[0]).name, '이/가')} {when} 휴무"
    if v.id.startswith("leg:"):
        a, b = v.places
        return f"{when} {trip.place(a).name}→{trip.place(b).name} 도보 {v.detail['minutes']}분(구간 상한 {v.detail['limit']}분)"
    if v.kind == "member":
        return f"{when} 하루 도보 {v.detail['minutes']}분(구성원 상한 {v.detail['limit']}분)"
    return f"{when} 하루 도보 {v.detail['minutes']}분(상한 {v.detail['limit']}분)"


def fact_sentence(ref: Reference, shown: int = 3) -> str:
    """코드 사실만으로 만든 문장(템플릿). 장소 이름은 화면에서만 쓴다."""
    noun = "후보예요" if ref.subject == "후보" else f"{ref.subject}이에요"
    confirmed = ref.confirmed
    if confirmed:
        listed = " / ".join(_violation_text(ref.trip, v) for v in confirmed[:shown])
        more = f" 외 {len(confirmed) - shown}개" if len(confirmed) > shown else ""
        sentence = f"확정 위반 {len(confirmed)}개가 남은 {noun}. 남은 위반: {listed}{more}."
    else:
        sentence = f"확정 위반이 없는 {noun}."
    if ref.checks:
        sentence += f" 영업 확인이 필요한 곳은 {len(ref.checks)}곳이에요."
    results = ref.goal_results
    if results:
        kept = ", ".join(goals_mod.label(ref.trip, r.goal) for r in results if r.met is True) or "없음"
        gave = ", ".join(goals_mod.label(ref.trip, r.goal) for r in results if r.met is not True)
        sentence += f" 지킨 목표: {kept}" + (f" · 못 지킨 목표: {gave}" if gave else "")
    return sentence


@dataclass(frozen=True)
class Guarded:
    reasons: tuple[str, ...]
    replacement: str


def guard(ref: Reference, raw_text: str) -> Optional[Guarded]:
    """모델 문장(슬롯 원문)이 사실과 어긋나면 대신 보일 코드 문장과 이유를, 아니면 None."""
    found = problems(ref, raw_text)
    return Guarded(tuple(found), fact_sentence(ref)) if found else None

"""작업 기록(pivot 8.3절) — 이해 → 확인 → 짜기 → 점검 → 재계획 → (찾기 → 옮겨 보기 → 비교 → 결정) → 끝 → 가정 → 결과를 단계마다 "무슨 역할"과 "누가"와 함께 찍는다. 순수 함수다.

한 단계는 `StepRecord`(stage, role, who, text)이고, 글로 찍으면 한 줄 `[단계] 역할(누가) 내용`이다. 역할은 다섯 가지로 정해져 있다:
해석(요청을 목표로) · 지휘(도구 고르기, 점검, 끝) · 계산(optimize, 수리) · 검증(코드가 사실과 맞춰 보기) · 결정(코드가 견줘 고른 것, 묻지 않고 둔 가정).

화면 문장은 코드 템플릿과 검증을 통과한 모델 생각(Step.thought)만 쓴다. 장소 이름은 화면에서만 나온다(모델 입력에는 없다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from agent.course import core, goals as goals_mod, verify
from agent.course.constants import DAY_TRAVEL_MAX_MIN, DAY_WALK_MAX_MIN, LEG_MAX_MIN, MEAL_CATEGORY, MEALS_PER_DAY_MIN
from agent.course.direct import BAD_FORMAT, NO_RESPONSE, RESOLVE_CLOSURE, RESOLVE_SPLIT, TIMEOUT, UNUSABLE, DirectResult, DirectStep
from agent.course.korean import attach, candidate_name, goals_sentence

MODEL, CODE, PERSON = "모델", "코드", "사람"
INTERPRET, DIRECT, COMPUTE, VERIFY, DECIDE = "해석", "지휘", "계산", "검증", "결정"
ROLES = (INTERPRET, DIRECT, COMPUTE, VERIFY, DECIDE)


_SIMPLE_WHO = {MODEL: "ai", CODE: "code", PERSON: "human"}


@dataclass(frozen=True)
class StepRecord:
    """작업 기록 한 단계. `who`는 화면 원문("모델", "모델 → 코드", "코드(목표 세우기 실패)")이고, 화면 API에는 by·by_detail로 나눠 나간다."""
    stage: str
    role: str
    who: str
    text: str

    @property
    def by(self) -> str:
        """ai | code | human. 섞여 있으면("모델 → 코드") 사람 > 모델 > 코드 순으로 대표값을 고른다."""
        if self.who in _SIMPLE_WHO:
            return _SIMPLE_WHO[self.who]
        return "human" if PERSON in self.who else "ai" if MODEL in self.who else "code"

    @property
    def by_detail(self) -> Optional[str]:
        return None if self.who in _SIMPLE_WHO else self.who

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "role": self.role, "by": self.by, "by_detail": self.by_detail, "text": self.text}

    def line(self) -> str:
        return f"[{self.stage}] {self.role}({self.who}) {self.text}"


def _rec(stage: str, role: str, who: str, text: str) -> StepRecord:
    assert role in ROLES, role
    return StepRecord(stage, role, who, text)


# 결과(outcome) 값 → 화면 문장. 화면에 enum 글자를 그대로 내지 않는다. {n}은 남은 확정 위반 수, {checks}는 영업시간을 모르는 곳 수(#1128).
OUTCOME_TEXT = {
    "solved": "확정 위반 없이 코스를 다 짰어요.",
    "solved_with_checks": "확정 위반은 없어요. 영업시간을 모르는 {checks}곳은 가게에 확인해 주세요.",
    "unresolved": "확정 위반이 {n}개 남은 채로 끝났어요.",
    "timeout": "시간이 다 되어 확정 위반이 {n}개 남은 채로 끝났어요.",
}
# 요청 목표가 없을 때(빈 요청, 「알아서 잘 짜줘」) 무엇을 기준으로 짜는지(#1128). 기준선의 날짜 균형·이동과 같은 말이다.
NO_GOALS_OPENING = "따로 지킬 목표는 없어요. 이동을 줄이고 날마다 장소 수를 고르게 나눠 짤게요."
NO_GOALS_CLOSING = "따로 지킬 목표 없이 이동을 줄이고 날마다 장소 수를 고르게 나눠 짰어요."
# 지도 목표 후보는 있었지만 목표 세우기가 하나도 고르지 않았을 때(#1131 B안). 후보가 아예 없을 때만 NO_GOALS_OPENING을 쓴다
MAP_NONE_OPENING = "지도에서 목표 후보를 찾았지만 이번 코스에는 세우지 않았어요. 이동을 줄이고 날마다 장소 수를 고르게 나눠 짤게요."


def _labels(by_id: dict[str, goals_mod.Goal], trip: core.Trip, ids: Sequence[str]) -> list[str]:
    return [goals_mod.label(trip, by_id[i]) for i in ids if i in by_id]


def _violations_sentence(confirmed: int) -> str:
    return "확정 위반은 없어요." if confirmed == 0 else f"확정 위반이 {confirmed}개 남아 있어요."


def _candidate_text(by_id: dict[str, goals_mod.Goal], trip: core.Trip, c: dict[str, Any]) -> str:
    """후보 한 개의 계산 결과 — 한 문장에 한 가지 사실. 후보 id(c1)는 화면에서 "1번 안"이다."""
    walk = c["walk"]
    return " ".join([
        f"{candidate_name(c['candidate_id'])}을 짰어요.",
        goals_sentence(_labels(by_id, trip, c["kept"]), _labels(by_id, trip, c["gave_up"])),
        f"하루 걷는 시간은 길어야 {walk['day_max']}분이에요." if walk["day_max"] else "걷는 구간이 없어요.",
        f"대중교통은 {walk['transit_legs']}구간 타요." if walk["transit_legs"] else "대중교통은 타지 않아요.",
        _violations_sentence(c["hard"]["confirmed"]),
    ])


def _names(trip: core.Trip, places: Sequence[str]) -> str:
    names = [trip.place(p).name for p in places]
    return ", ".join(names[:2]) + (f" 외 {len(names) - 2}곳" if len(names) > 2 else "")


def _tried_text(t: dict[str, Any]) -> str:
    kept = f"목표 {t['total']}개 중 {t['kept']}개를 지키고 " if t["total"] else ""
    return f"{kept}확정 위반은 {t['confirmed']}개예요." if t["confirmed"] else f"{kept}확정 위반이 없어요."


_COMPARE = "확정 위반이 적은 쪽, 같으면 지킨 목표가 많은 쪽으로 견주면"


def resolved_records(trip: core.Trip, by_id: dict[str, goals_mod.Goal], step: DirectStep) -> list[StepRecord]:
    """코드가 푼 단계(#1131) 하나를 찾기 → 옮겨 보기 → 비교 → 결정 줄로. 결정 문장은 direct가 검증을 거쳐 만든 것(step.note)이다."""
    d = step.result.data
    day = lambda alias: core.day_label(trip, alias)
    if step.call.get("tool") == RESOLVE_CLOSURE:
        goal = by_id.get(d["goal_after"])
        name = f"‘{goals_mod.label(trip, goals_mod.retarget(goal, d['closed_day']))}’" if goal else "그 목표"
        closed = f"{attach(_names(trip, d['closed_places']), '이/가')} 쉬어요" if d["closed_places"] else "그날 쉬어요"
        out = [_rec("찾기", VERIFY, CODE, f"{name} 목표의 {day(d['closed_day'])}엔 {closed}. 여는 날은 "
                    f"{', '.join(day(t['day']) for t in d['tried'])}이에요.")]
        out += [_rec("옮겨 보기", COMPUTE, CODE, f"{attach(day(t['day']), '으로/로')} 옮겨 짜 보면 {_tried_text(t)}") for t in d["tried"]]
        best = day(d["chosen_day"])
    else:
        out = [_rec("찾기", VERIFY, CODE, f"{day(d['day'])}엔 이동 위반이 남았어요. 이동을 줄이는 나누기를 {len(d['tried'])}가지 찾았어요.")]
        out += [_rec("옮겨 보기", COMPUTE, CODE, f"{attach(_names(trip, t['places']), '을/를')} {attach(day(t['to_day']), '으로/로')} 옮겨 짜 보면 {_tried_text(t)}")
                for t in d["tried"]]
        best = f"{attach(_names(trip, d['moved']), '을/를')} {attach(day(d['to_day']), '으로/로')} 옮기는 것"
    out.append(_rec("비교", VERIFY, CODE, f"{_COMPARE} {attach(best, '이/가')} 가장 나아요."))
    if step.guard:
        out.append(_rec("검증", VERIFY, CODE, "코드가 만든 문장이 결과와 맞지 않아 결과 문장으로 바꿨어요. " + ". ".join(step.guard) + "."))
    out.append(_rec("결정", DECIDE, CODE, step.note or ""))
    return out


def meal_less_text(trip: core.Trip, day_index: int) -> str:
    """식사할 곳이 없는 날의 확인 문장. 정하는 곳은 core.meal_less_days 하나다. 세 경우로 나눈다(#1008 K2): 확정 리스트에 식당이 0곳 /
    있지만 날마다 둘 만큼은 모자람 / 둘 만큼 있는데 그날에 배정되지 않고 다른 날에 놓임. 있는데 "리스트에 없다"고 쓰면 사실과 다르다."""
    day = core.day_label(trip, core.day_alias(day_index))
    meals = sum(p.category == MEAL_CATEGORY for p in trip.places)
    if meals == 0:
        return f"{day}에는 식사할 곳이 확정 리스트에 없어요."
    if meals < len(trip.days) * MEALS_PER_DAY_MIN:
        return f"{day}에는 식사할 곳이 없어요. 확정 리스트의 식당이 모자라 이날은 비었어요."
    return f"{day}에는 식사할 곳이 배정되지 않았어요. 확정 리스트에는 있지만 다른 날에 놓였어요."


def _understood(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], candidates: Sequence[goals_mod.MapCandidate] = (),
) -> str:
    """「이해」 줄. 목표로 바꾸지 않은 조각은 종류가 정해진 것(시간, 하루 비우기)이면 코드의 고정 이유 문장을 쓰고 조각 원문은 넣지 않는다(#1128).
    종류를 모르는 조각만 「…」는 판단할 수 없다고 쓴다. 지도 목표는 출처와 근거를 밝힌다(#1131 B안) — 근거는 키 이름·사람 수·장소 수뿐이다."""
    reasons = [goals_mod.piece_reason(u) for u in unmatched]
    asked = [g for g in goals if g.origin != "map"]
    mapped = [g for g in goals if g.origin == "map"]
    if asked:
        head = ", ".join(goals_mod.label(trip, g) for g in asked) + "."
    elif unmatched:
        head = "요청에서 지킬 목표를 찾지 못했어요."
    elif mapped:
        head = ""
    else:
        head = MAP_NONE_OPENING if candidates else NO_GOALS_OPENING
    text = (head + "".join(f" {attach(f'「{u}」', '은/는')} 그대로는 판단할 수 없어요." for u, r in zip(unmatched, reasons) if r is None)
            + "".join(f" {goals_mod.PIECE_REASONS[r]}" for r in dict.fromkeys(r for r in reasons if r)))
    if mapped:
        by_id = {c.id: c for c in candidates}
        lead = "요청이 없어서 지도에서 목표를 세웠어요: " if not asked and not unmatched else "지도에서도 목표를 세웠어요: "
        basis = ", ".join(goals_mod.evidence_text(by_id[g.candidate]) for g in mapped if g.candidate in by_id)
        text += (" " if text else "") + lead + ", ".join(goals_mod.label(trip, g, mark=False) for g in mapped) + "." + (f" (근거: {basis})" if basis else "")
    return text


# 모델이 실패해 코드가 이어받은 단계(#1131 D안). 원인 종류만 가르고 예외 메시지나 모델 원문은 쓰지 않는다
FAILURE_TEXT = {
    TIMEOUT: "모델 응답이 시간 안에 오지 않아",
    BAD_FORMAT: "모델 응답의 형식이 맞지 않아",
    NO_RESPONSE: "모델 응답이 없어",
    UNUSABLE: "모델이 고른 도구를 더 쓸 수 없어",
}
_TAKEN_OVER = {"optimize": "이번 단계는 코드가 이어서 짰어요.", "finish": "이번 단계는 코드가 이어서 골랐어요."}
GOALS_FAILED_TEXT = "목표를 세우지 못했어요. 요청 목표 없이 기본 기준으로 짜요."


def _row_text(trip: core.Trip, by_id: dict[str, goals_mod.Goal], r: dict[str, Any]) -> str:
    """비교 줄 하나(#1131 C안) — 후보의 성격, 지킨 목표 수, 확정 위반, 하루 최대 도보, 대중교통 구간. 숫자와 이름은 코드가 넣는다."""
    style = ("요청 목표 없이 이동과 날짜 균형 먼저" if r["balanced"]
             else f"‘{goals_mod.label(trip, by_id[r['focus']])}’ 먼저" if r["focus"] in by_id else "요청 목표를 최대한")
    walk = f"하루 도보 최대 {r['walk_day_max']}분" if r["walk_day_max"] else "걷는 구간 없음"
    return (f"{candidate_name(r['candidate_id'])}({style}): 목표 {r['total']}개 중 {len(r['kept'])}개 지킴, "
            f"확정 위반 {r['confirmed']}개, {walk}, 대중교통 {r['transit_legs']}구간.")


def _quoted(trip: core.Trip, by_id: dict[str, goals_mod.Goal], ids: Sequence[str]) -> str:
    return ", ".join(f"‘{goals_mod.label(trip, by_id[i])}’" for i in ids if i in by_id)


def decision_text(trip: core.Trip, by_id: dict[str, goals_mod.Goal], data: dict[str, Any]) -> str:
    """끝 줄의 결정 이유 — 다른 후보마다 얻은 것과 잃은 것 한 마디씩(#1131 C안). 「2번 안은 걷기는 짧지만 ‘…’ 목표를 못 지켜서
    1번 안으로 정했어요.」 고른 안이 코드 규칙으로도 가장 나으면 남은 차이를 「영업 확인, 목표 순서, 날짜 균형까지 견주면」으로 말하고,
    모델이 다른 안을 골랐으면 그렇다고 쓴다. 코스가 같은 후보는 한 번만 본다."""
    rows = {r["candidate_id"]: r for r in data["compare"]}
    chosen = rows[data["candidate_id"]]
    clauses = []
    for o in data["compare"]:
        if o is chosen:
            continue
        good = ([f"{_quoted(trip, by_id, [g for g in o['kept'] if g not in chosen['kept']])} 목표는 지키지만"]
                if any(g not in chosen["kept"] for g in o["kept"]) else
                ["걷기는 짧지만"] if o["walk_day_max"] < chosen["walk_day_max"] else
                ["대중교통은 적지만"] if o["transit_legs"] < chosen["transit_legs"] else [])
        missed = [g for g in chosen["kept"] if g not in o["kept"]]
        bad = ("확정 위반이 더 남아서" if o["confirmed"] > chosen["confirmed"] else
               f"{_quoted(trip, by_id, missed)} 목표를 못 지켜서" if missed else
               "하루 걷는 시간이 더 길어서" if o["walk_day_max"] > chosen["walk_day_max"] else
               "대중교통 구간이 더 많아서" if o["transit_legs"] > chosen["transit_legs"] else
               "영업 확인, 목표 순서, 날짜 균형까지 견주면 덜 맞아서" if data["code_best"] == chosen["candidate_id"] else
               "모델의 판단으로")
        clauses.append(" ".join([attach(candidate_name(o["candidate_id"]), "은/는"), *good, bad]))
    return f"{', '.join(clauses)} {attach(candidate_name(chosen['candidate_id']), '으로/로')} 정했어요."


class Narrator:
    """지휘 루프의 단계를 하나씩 받아 작업 기록으로 바꾼다. 앞 단계에서 세는 값(짜기 횟수 등)을 들고 있어서 단계 순서대로 불러야 한다.
    진행 중 저장(on_step)과 끝난 뒤 한 번에 찍기(render)가 같은 코드를 쓴다."""

    def __init__(
        self, trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], *, understood_by: str = MODEL,
        candidates: Sequence[goals_mod.MapCandidate] = (), goals_failure: Optional[str] = None,
    ):
        """goals_failure: 목표 세우기 모델이 실패했으면 원인 종류(direct.failure_kind) — 코드가 이어받았다는 줄을 남긴다(#1131 D안)."""
        self.trip = trip
        self.by_id = {g.id: g for g in goals}
        self._opening = [_rec("이해", INTERPRET, understood_by, "이렇게 이해했어요: " + _understood(trip, goals, unmatched, candidates))]
        if goals_failure is not None:
            self._opening.append(_rec("대행", INTERPRET, CODE, f"{FAILURE_TEXT[goals_failure]} {GOALS_FAILED_TEXT}"))
        self.optimized = 0
        self.redo = False                       # 코드가 쉬는 날·이동을 푼 뒤 처음 짜는 optimize는 "다시 짜기"다
        self.reviewing = False                  # 직전 단계가 후보를 돌려줬다 — 이번 모델 생각은 그 결과의 점검이다

    def opening(self) -> list[StepRecord]:
        return list(self._opening)

    def step(self, step: DirectStep, *, goals: Sequence[goals_mod.Goal]) -> list[StepRecord]:
        """goals는 이 단계까지의 것(코드가 쉬는 날을 풀어 바뀐 목표도 이름을 붙일 수 있게)."""
        self.by_id.update({g.id: g for g in goals})
        trip, by_id, out = self.trip, self.by_id, []
        tool = step.call.get("tool")
        if tool in (RESOLVE_CLOSURE, RESOLVE_SPLIT):
            self.redo = True
            return resolved_records(trip, by_id, step)
        if step.substituted_for:                # 모델이 실패해 코드가 이어받았다(#1131 D안) — 원인 종류와 고정 문구만
            out.append(_rec("대행", DIRECT, CODE, f"{FAILURE_TEXT[step.substituted_for.get('failure', NO_RESPONSE)]} "
                            f"{_TAKEN_OVER.get(tool, '이번 단계는 코드가 이어받았어요.')}"))
        if tool == "check_goals":
            return out + [_rec("확인", VERIFY, CODE, sentence) for sentence in step.result.data["sentences"]]
        if step.thought:
            stage = "다시 짜기" if self.redo and tool == "optimize" else "짜기" if not self.reviewing and tool == "optimize" and self.optimized == 0 else (
                "재계획" if tool == "optimize" else "점검")
            if step.guard:                      # 모델 문장은 화면에 내지 않는다 — 코드 사실로 만든 문장과, 바꿨다는 기록만
                out.append(_rec("검증", VERIFY, CODE, "모델이 쓴 문장이 결과와 맞지 않아 코드가 만든 문장으로 바꿨어요. "
                                + ". ".join(step.guard) + "."))
                out.append(_rec(stage, DIRECT, CODE, step.thought))
            else:
                out.append(_rec(stage, DIRECT, f"{MODEL} → {CODE}" if tool == "optimize" else MODEL, step.thought))
        if tool == "optimize" and step.result.ok:
            self.optimized += 1
            self.reviewing = True
            stage_name = "다시 짜기" if self.redo else "짜기"
            self.redo = False
            for c in step.result.data["candidates"]:
                out.append(_rec(stage_name, COMPUTE, CODE, _candidate_text(by_id, trip, c)))
        elif tool == "lock" and step.result.ok:
            out.append(_rec("고정", DIRECT, MODEL, "장소를 한 날에 고정했어요"))
        elif tool == "finish" and step.result.ok:
            self.reviewing = False
            data = step.result.data
            ended = f"{attach(candidate_name(data['candidate_id']), '으로/로')} 정했어요."
            if data.get("compare") is not None:      # 목표가 있으면 견준 것을 남긴다(#1131 C안). 코스가 하나뿐이면 지어내지 않는다
                if data["distinct"] < 2:
                    out.append(_rec("비교", VERIFY, CODE, "다른 짜임을 찾지 못했어요. 이 장소들로는 코스가 하나로 모여요."))
                else:
                    out += [_rec("비교", VERIFY, CODE, _row_text(trip, by_id, r)) for r in data["compare"]]
                    ended = decision_text(trip, by_id, data)
            out.append(_rec("끝", DIRECT, MODEL if step.by == "model" else CODE, ended))
        return out

    def closing(self, result: DirectResult) -> list[StepRecord]:
        self.by_id.update({g.id: g for g in result.state.goals})
        out = []
        if result.chosen.walk_infeasible:
            out.append(_rec("결과", COMPUTE, CODE, f"도보 구간 {LEG_MAX_MIN}분·하루 도보 {DAY_WALK_MAX_MIN}분·하루 이동 {DAY_TRAVEL_MAX_MIN}분(대중교통 포함, 약) 상한과 "
                            "구성원 조건, 확인된 휴무를 모두 지키는 순서는 이 장소 구성으로는 없다는 것을 모든 경우를 따져 확인했어요. 장소나 날짜 수가 바뀌어야 풀려요."))
        for i in core.meal_less_days(self.trip, result.course):     # 식당이 없는 날 알림(#918) — 장소를 더하거나 빼지 않고 알리기만 한다
            out.append(_rec("확인", VERIFY, CODE, meal_less_text(self.trip, i)))
        ref = verify.Reference(self.trip, result.state.hours, result.course, result.violations, result.state.goals)
        if (assumed := verify.assumption_sentence(ref)) is not None:    # 묻지 않고 정한 것(#1131) — 결과의 「가게에 확인해 주세요」와 짝이다
            out.append(_rec("가정", DECIDE, CODE, assumed))
        met = [r.goal.id for r in result.goal_results if r.met is True]
        gave = [r.goal.id for r in result.goal_results if r.met is not True]
        out.append(_rec("결과", VERIFY, CODE, " ".join([
            goals_sentence(_labels(self.by_id, self.trip, met), _labels(self.by_id, self.trip, gave)) if result.goal_results else NO_GOALS_CLOSING,
            OUTCOME_TEXT.get(result.outcome, "결과를 정하지 못했어요.").format(
                n=core.hard_score(result.violations)[0], checks=len(core.find_checks(self.trip, result.course, result.state.hours))),
        ])))
        return out


def records(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], result: DirectResult,
    *, understood_by: str = MODEL, candidates: Sequence[goals_mod.MapCandidate] = (),
) -> list[StepRecord]:
    """끝난 결과 전체를 한 번에 작업 기록으로(진행 중 저장이 내보낸 것과 같은 순서·내용)."""
    narrator = Narrator(trip, goals, unmatched, understood_by=understood_by, candidates=candidates)
    out = narrator.opening()
    for step in result.steps:
        out += narrator.step(step, goals=result.state.goals)
    return out + narrator.closing(result)


def render(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], result: DirectResult,
    *, understood_by: str = MODEL, candidates: Sequence[goals_mod.MapCandidate] = (),
) -> list[str]:
    """평가·시연 스크립트용 글 줄 `[단계] 역할(누가) 내용`."""
    return [r.line() for r in records(trip, goals, unmatched, result, understood_by=understood_by, candidates=candidates)]

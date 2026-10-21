"""작업 기록(pivot 8.3절) — 이해 → 확인 → 짜기 → 점검 → 재계획 → 질문 → 끝을 단계마다 "무슨 역할"과 "누가"와 함께 찍는다. 순수 함수다.

한 단계는 `StepRecord`(stage, role, who, text)이고, 글로 찍으면 한 줄 `[단계] 역할(누가) 내용`이다. 역할은 다섯 가지로 정해져 있다:
해석(요청을 목표로) · 지휘(도구 고르기, 점검, 끝) · 계산(optimize, 수리) · 검증(코드가 사실과 맞춰 보기) · 결정(사람의 답 또는 기본값).

화면 문장은 코드 템플릿과 검증을 통과한 모델 생각(Step.thought)만 쓴다. 장소 이름은 화면에서만 나온다(모델 입력에는 없다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.constants import DAY_TRAVEL_MAX_MIN, LEG_MAX_MIN
from agent.course.direct import DirectResult, DirectStep, Question
from agent.course.korean import attach

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


def _kept_text(by_id: dict[str, goals_mod.Goal], trip: core.Trip, ids: Sequence[str]) -> str:
    return ", ".join(goals_mod.label(trip, by_id[i]) for i in ids if i in by_id) or "없음"


class Narrator:
    """지휘 루프의 단계를 하나씩 받아 작업 기록으로 바꾼다. 앞 단계에서 세는 값(짜기 횟수 등)을 들고 있어서 단계 순서대로 불러야 한다.
    진행 중 저장(on_step)과 끝난 뒤 한 번에 찍기(render)가 같은 코드를 쓴다."""

    def __init__(self, trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], *, understood_by: str = MODEL):
        self.trip = trip
        self.by_id = {g.id: g for g in goals}
        self._opening = _rec("이해", INTERPRET, understood_by, "이렇게 이해했어요: "
                             + (" · ".join(goals_mod.label(trip, g) for g in goals) or "요청 목표 없음")
                             + "".join(f" · {attach(f'「{u}」', '은/는')} 그대로는 판단할 수 없어요" for u in unmatched))
        self.optimized = 0
        self.redo = False                       # 쉬는 날 질문에 답한 뒤 처음 짜는 optimize는 "다시 짜기"다
        self.reviewing = False                  # 직전 단계가 후보를 돌려줬다 — 이번 모델 생각은 그 결과의 점검이다

    def opening(self) -> list[StepRecord]:
        return [self._opening]

    def step(self, step: DirectStep, *, goals: Sequence[goals_mod.Goal], questions: Sequence[Question]) -> list[StepRecord]:
        """goals·questions는 이 단계까지의 것(질문의 답으로 바뀐 목표도 이름을 붙일 수 있게)."""
        self.by_id.update({g.id: g for g in goals})
        trip, by_id, out = self.trip, self.by_id, []
        tool = step.call.get("tool")
        if step.substituted_for and step.substituted_for["error"] != "QUESTION_OPENED_BY_CODE":
            out.append(_rec("대행", DIRECT, CODE, f"모델의 {step.substituted_for['call'].get('tool')} 호출이 "
                            f"{step.substituted_for['error']}라 코드 규칙이 대신 {attach(tool, '을/를')} 했어요"))
        if tool == "check_goals":
            return out + [_rec("확인", VERIFY, CODE, sentence) for sentence in step.result.data["sentences"]]
        if step.thought:
            stage = "다시 짜기" if self.redo and tool == "optimize" else "짜기" if not self.reviewing and tool == "optimize" and self.optimized == 0 else (
                "재계획" if tool == "optimize" else "점검")
            if step.guard:                      # 모델 문장은 화면에 내지 않는다 — 코드 사실로 만든 문장과, 바꿨다는 기록만
                out.append(_rec("검증", VERIFY, CODE, "모델이 쓴 문장이 결과와 맞지 않아 코드가 만든 문장으로 바꿨어요 — "
                                + " · ".join(step.guard)))
                out.append(_rec(stage, DIRECT, CODE, step.thought))
            else:
                out.append(_rec(stage, DIRECT, f"{MODEL} → {CODE}" if tool == "optimize" else MODEL, step.thought))
        if tool == "optimize" and step.result.ok:
            self.optimized += 1
            self.reviewing = True
            stage_name = "다시 짜기" if self.redo else "짜기"
            self.redo = False
            for c in step.result.data["candidates"]:
                out.append(_rec(stage_name, COMPUTE, CODE, f"후보 {c['candidate_id']}: 지킴 {_kept_text(by_id, trip, c['kept'])} · "
                                f"못 지킴 {_kept_text(by_id, trip, c['gave_up'])} · 하루 최대 도보 {c['walk']['day_max']}분 · "
                                f"확정 위반 {c['hard']['confirmed']}"))
        elif tool == "lock" and step.result.ok:
            out.append(_rec("고정", DIRECT, MODEL, "장소를 한 날에 고정했어요"))
        elif tool == "ask_requester":
            if not step.result.ok:
                out.append(_rec("질문", DIRECT, MODEL, f"질문을 열지 못했어요({step.result.error})"))
                return out
            q = next(q for q in questions if q.question_id == step.result.data["question_id"])
            opener = f"코드가 열고 {MODEL}이 고름 → {PERSON}" if step.by == "model" else f"코드가 열음 → {PERSON}"
            if q.kind == "choose_day":
                opener = f"코드가 열고 {MODEL}이 날짜를 제안 → {PERSON}" if step.by == "model" else f"코드가 열음 → {PERSON}"
                out.append(_rec("질문", DIRECT, opener, f"{q.text} · 선택지 {' / '.join(q.option_labels)} · 기본값 {q.option_labels[0]}({q.default_reason})"))
                out.append(_rec("답", DECIDE, CODE, f"답이 없어 기본값으로 이어 가요: {step.result.data['answer']}"))
                self.redo = True
            else:
                out.append(_rec("질문", DIRECT, opener, f"{q.text} · 선택지 {' / '.join(q.options)} · 기본값 {q.default}(답이 없어 기본값으로 이어 가요)"))
        elif tool == "finish" and step.result.ok:
            self.reviewing = False
            note = step.result.data.get("note")
            out.append(_rec("끝", DIRECT, MODEL if step.by == "model" else CODE,
                            f"후보 {step.result.data['candidate_id']}로 끝내요" + (f" — {note}" if note else "")))
        return out

    def closing(self, result: DirectResult) -> list[StepRecord]:
        self.by_id.update({g.id: g for g in result.state.goals})
        out = []
        if result.chosen.walk_infeasible:
            out.append(_rec("결과", COMPUTE, CODE, f"구간 도보 {LEG_MAX_MIN}분·하루 도보 {DAY_TRAVEL_MAX_MIN}분 상한을 모두 지키는 순서는 이 장소 구성으로는 "
                            "없다는 것을 모든 경우를 따져 확인했어요 — 장소나 날짜 수가 바뀌어야 풀려요"))
        met = [r.goal.id for r in result.goal_results if r.met is True]
        out.append(_rec("결과", VERIFY, CODE, f"지킨 목표: {_kept_text(self.by_id, self.trip, met)} · 확정 위반 "
                        f"{core.hard_score(result.violations)[0]} · 결과 {result.outcome}"))
        return out


def records(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], result: DirectResult,
    *, understood_by: str = MODEL,
) -> list[StepRecord]:
    """끝난 결과 전체를 한 번에 작업 기록으로(진행 중 저장이 내보낸 것과 같은 순서·내용)."""
    narrator = Narrator(trip, goals, unmatched, understood_by=understood_by)
    out = narrator.opening()
    for step in result.steps:
        out += narrator.step(step, goals=result.state.goals, questions=result.questions)
    return out + narrator.closing(result)


def render(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], result: DirectResult,
    *, understood_by: str = MODEL,
) -> list[str]:
    """평가·시연 스크립트용 글 줄 `[단계] 역할(누가) 내용`."""
    return [r.line() for r in records(trip, goals, unmatched, result, understood_by=understood_by)]

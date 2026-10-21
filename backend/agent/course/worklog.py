"""작업 기록(pivot 8.3절) — 이해 → 확인 → 짜기 → 점검 → 재계획 → 질문 → 끝을 단계마다 "무슨 역할"과 "누가"와 함께 찍는다. 순수 함수다.

한 줄은 `[단계] 역할(누가) 내용`이다. 역할은 다섯 가지로 정해져 있다:
해석(요청을 목표로) · 지휘(도구 고르기, 점검, 끝) · 계산(optimize, 수리) · 검증(코드가 사실과 맞춰 보기) · 결정(사람의 답 또는 기본값).

화면 문장은 코드 템플릿과 검증을 통과한 모델 생각(Step.thought)만 쓴다. 장소 이름은 화면에서만 나온다(모델 입력에는 없다).
"""

from __future__ import annotations

from typing import Optional, Sequence

from agent.course import core, goals as goals_mod
from agent.course.constants import DAY_TRAVEL_MAX_MIN, LEG_MAX_MIN
from agent.course.direct import DirectResult
from agent.course.korean import attach

MODEL, CODE, PERSON = "모델", "코드", "사람"
INTERPRET, DIRECT, COMPUTE, VERIFY, DECIDE = "해석", "지휘", "계산", "검증", "결정"
ROLES = (INTERPRET, DIRECT, COMPUTE, VERIFY, DECIDE)


def _line(stage: str, role: str, who: str, text: str) -> str:
    assert role in ROLES, role
    return f"[{stage}] {role}({who}) {text}"


def _kept_text(by_id: dict[str, goals_mod.Goal], trip: core.Trip, ids: Sequence[str]) -> str:
    return ", ".join(goals_mod.label(trip, by_id[i]) for i in ids if i in by_id) or "없음"


def render(
    trip: core.Trip, goals: Sequence[goals_mod.Goal], unmatched: Sequence[str], result: DirectResult,
    *, understood_by: str = MODEL,
) -> list[str]:
    by_id = {g.id: g for g in (*goals, *result.state.goals)}       # 질문의 답으로 바뀐 목표도 이름을 붙일 수 있게
    out = [_line("이해", INTERPRET, understood_by, "이렇게 이해했어요: "
                 + (" · ".join(goals_mod.label(trip, g) for g in goals) or "요청 목표 없음")
                 + "".join(f" · {attach(f'「{u}」', '은/는')} 그대로는 판단할 수 없어요" for u in unmatched))]
    optimized = 0
    redo = False                            # 쉬는 날 질문에 답한 뒤 처음 짜는 optimize는 "다시 짜기"다
    reviewing = False                       # 직전 단계가 후보를 돌려줬다 — 이번 모델 생각은 그 결과의 점검이다
    for step in result.steps:
        tool = step.call.get("tool")
        if step.substituted_for and step.substituted_for["error"] != "QUESTION_OPENED_BY_CODE":
            out.append(_line("대행", DIRECT, CODE, f"모델의 {step.substituted_for['call'].get('tool')} 호출이 "
                             f"{step.substituted_for['error']}라 코드 규칙이 대신 {attach(tool, '을/를')} 했어요"))
        if tool == "check_goals":
            for sentence in step.result.data["sentences"]:
                out.append(_line("확인", VERIFY, CODE, sentence))
            continue
        if step.thought:
            stage = "다시 짜기" if redo and tool == "optimize" else "짜기" if not reviewing and tool == "optimize" and optimized == 0 else (
                "재계획" if tool == "optimize" else "점검")
            out.append(_line(stage, DIRECT, f"{MODEL} → {CODE}" if tool == "optimize" else MODEL, step.thought))
        if tool == "optimize" and step.result.ok:
            optimized += 1
            reviewing = True
            stage_name = "다시 짜기" if redo else "짜기"
            redo = False
            for c in step.result.data["candidates"]:
                out.append(_line(stage_name, COMPUTE, CODE, f"후보 {c['candidate_id']}: 지킴 {_kept_text(by_id, trip, c['kept'])} · "
                                 f"못 지킴 {_kept_text(by_id, trip, c['gave_up'])} · 하루 최대 도보 {c['walk']['day_max']}분 · "
                                 f"확정 위반 {c['hard']['confirmed']}"))
        elif tool == "lock" and step.result.ok:
            out.append(_line("고정", DIRECT, MODEL, "장소를 한 날에 고정했어요"))
        elif tool == "ask_requester":
            if not step.result.ok:
                out.append(_line("질문", DIRECT, MODEL, f"질문을 열지 못했어요({step.result.error})"))
                continue
            q = next(q for q in result.questions if q.question_id == step.result.data["question_id"])
            opener = f"코드가 열고 {MODEL}이 고름 → {PERSON}" if step.by == "model" else f"코드가 열음 → {PERSON}"
            if q.kind == "choose_day":
                opener = f"코드가 열고 {MODEL}이 날짜를 제안 → {PERSON}" if step.by == "model" else f"코드가 열음 → {PERSON}"
                out.append(_line("질문", DIRECT, opener, f"{q.text} · 선택지 {' / '.join(q.option_labels)} · 기본값 {q.option_labels[0]}({q.default_reason})"))
                out.append(_line("답", DECIDE, CODE, f"답이 없어 기본값으로 이어 가요: {step.result.data['answer']}"))
                redo = True
            else:
                out.append(_line("질문", DIRECT, opener, f"{q.text} · 선택지 {' / '.join(q.options)} · 기본값 {q.default}(답이 없어 기본값으로 이어 가요)"))
        elif tool == "finish" and step.result.ok:
            reviewing = False
            note = step.result.data.get("note")
            out.append(_line("끝", DIRECT, MODEL if step.by == "model" else CODE,
                             f"후보 {step.result.data['candidate_id']}로 끝내요" + (f" — {note}" if note else "")))
    if result.chosen.walk_infeasible:
        out.append(_line("결과", COMPUTE, CODE, f"구간 도보 {LEG_MAX_MIN}분·하루 도보 {DAY_TRAVEL_MAX_MIN}분 상한을 모두 지키는 순서는 이 장소 구성으로는 "
                         "없다는 것을 모든 경우를 따져 확인했어요 — 장소나 날짜 수가 바뀌어야 풀려요"))
    met = [r.goal.id for r in result.goal_results if r.met is True]
    out.append(_line("결과", VERIFY, CODE, f"지킨 목표: {_kept_text(by_id, trip, met)} · 확정 위반 "
                     f"{core.hard_score(result.violations)[0]} · 결과 {result.outcome}"))
    return out

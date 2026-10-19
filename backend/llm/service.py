"""backend/llm 비즈니스 로직 — 모델 호출 3곳(plan_evidence/label_place/rank_candidates)과 v2 에이전트 호출
(agent_diagnose #532, agent_advise_run #587 — 맨 아래 두 절. 신호 순위는 #582에서 agent의 코드 규칙으로 옮겼다).

② plan_evidence는 넘겨받은 planner로 부른다 — real_evidence_planner는 Luna를 실제로 부르고(#116), 기존
passthrough_planner는 입력을 스키마로 검증·통과하는 스텁이다(LLM_MODE로 고르는 곳은 recommend/deps.py, #219). ③-a-1 label_place, ③-b rank_candidates는 아직 고정 응답
스텁이다(backend/llm/CLAUDE.md "우선순위" 절) — 시그니처는 최종 형태(입력=구조화 가능한 값,
출력=schemas.py 스키마)로 미리 맞춰둔다.

세 함수 모두 값을 지어내지 않는다: 판단 근거가 없으면 항상 unknown/None을 반환한다
(backend/llm/CLAUDE.md "넘지 말 것"). 실격 여부 판단·unknown_policy 적용은 이 모듈의
책임이 아니다 — recommend가 한다(가드레일 7).
"""

import json
import logging
import re
import unicodedata
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, Union

from common.errors import AppError
from llm.client import (
    LlmCallError, call_agent_advice_turn, call_agent_diagnosis_turn, call_planner, get_client, metering,
)
from llm.prompts import (
    ADVICE_MAX_TOOL_CALLS, AGENT_ADVISE_RUN_PROMPT, AGENT_DIAGNOSE_PROMPT, DIAGNOSIS_MAX_TOOL_CALLS, DIAGNOSIS_TOOLS,
    RUN_ADVICE_TOOLS, STRUCTURE_REASONS_MAX_CALLS, diagnosis_tools, run_advice_tools,
)
from llm.schemas import (
    AgentCallFailed, AgentReply, DiagnosisOutput, EvidenceLine, FactKey, PlaceFactLabel, PlannedCondition, PlannedReason,
    PlanningOutput, RankedCandidate, RunAdviceOutput,
)

log = logging.getLogger("pingo.llm")

# 입력 글마다 근거 줄 묶음 하나(#419) — 바깥 리스트는 입력과 개수·순서가 같다.
EvidencePlanner = Callable[[Sequence[Mapping[str, Any]]], list[list[EvidenceLine]]]


def _flatten_string_values(data: Mapping[str, Any]) -> list[str]:
    """place_raw_facts 안의 모든 문자열 값을 평탄화한다.

    evidence 대조에 쓸 "실제로 원자료에 있던 텍스트 전체" 목록을 만든다.
    중첩된 list/dict 안의 문자열까지 재귀적으로 뽑아낸다(예: 리뷰 텍스트 배열).
    """
    flattened: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            flattened.append(value)
        elif isinstance(value, Mapping):
            for nested in value.values():
                _walk(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                _walk(nested)

    for value in data.values():
        _walk(value)
    return flattened


class PlanEvidenceFailed(AppError):
    """②가 실패했다 — 사유를 "조건 없음"으로 간주해 통과시키지 않고 추천을 중단한다(가드레일 4·8).
    기존 에러 코드 RECOMMEND_FAILED(500)로 나간다."""

    def __init__(self, reason: str):
        super().__init__("RECOMMEND_FAILED", detail={"stage": "plan_evidence", "reason": reason})


MIN_RADIUS_M = 50
MAX_RADIUS_M = 20_000


_INVISIBLE = re.compile(r"[​-‏⁠﻿­\s]+")


def _normalize(text: str) -> str:
    """비교용 정규화 — NFC로 합치고 제로폭 문자·공백을 전부 뺀다. 눈에 같은 글자(자모 분리형 한글 등)를
    같다고 본다. 결과 text에는 쓰지 않는다(결과는 항상 입력 원문)."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFC", text))


def _merge_conditions(conditions: Sequence[PlannedCondition]) -> list[tuple[str, Optional[bool]]]:
    """같은 키가 한 글에서 여러 번 나오면 하나로 합친다(#419). 순서는 처음 나온 순서다.
    방향이 엇갈리면(true와 false) 어느 쪽인지 지어내지 않고 null이다."""
    directions: dict[str, set[bool]] = {}
    for condition in conditions:
        seen = directions.setdefault(condition.fact_key, set())
        if condition.wants is not None:
            seen.add(condition.wants)
    merged: list[tuple[str, Optional[bool]]] = []
    for key, seen in directions.items():
        if len(seen) == 1:
            wants: Optional[bool] = next(iter(seen))
        else:
            wants = None
        merged.append((key, wants))
    return merged


def _split_reason(base: EvidenceLine, planned: PlannedReason) -> list[EvidenceLine]:
    """입력 글 한 줄 → 근거 줄 1개 이상(#419). 조건이 없으면 키 없는 줄 하나, 여럿이면 조건마다 하나.

    입력에 fact_key가 이미 있으면(칩처럼 정해진 줄) 나누지 않는다 — 키는 입력 값이고, 방향은 입력에
    없을 때만 같은 키 조건에서 가져온다. 반경은 입력 글당 하나라 첫 줄에만 붙인다."""
    radius = planned.circle_radius_m
    if radius is None or not MIN_RADIUS_M <= radius <= MAX_RADIUS_M:
        radius = base.circle_radius_m

    if base.fact_key is not None:
        same_key = [c for c in planned.conditions if c.fact_key == base.fact_key]
        planned_wants = _merge_conditions(same_key)[0][1] if same_key else None
        conditions = [(base.fact_key, base.wants if base.wants is not None else planned_wants)]
    else:
        conditions = _merge_conditions(planned.conditions) or [(None, None)]

    return [
        base.model_copy(update={
            "fact_key": fact_key,
            "wants": wants if fact_key is not None else None,
            "circle_radius_m": radius if position == 0 else None,
            "circle_anchor_pin_id": base.circle_anchor_pin_id if position == 0 else None,
        })
        for position, (fact_key, wants) in enumerate(conditions)
    ]


def merge_planned(
    inputs: Sequence[Mapping[str, Any]], output: PlanningOutput
) -> list[list[EvidenceLine]]:
    """모델 응답을 입력에 합친다(순수 함수). 돌려주는 바깥 리스트는 입력과 개수·순서가 같다 — i번째
    묶음이 i번째 입력 글에서 나온 근거 줄들이고, 묶음마다 1줄 이상이다(#419).

    모델이 정하는 건 조건(fact_key·wants, 입력에 없을 때)과 circle_radius_m뿐이다 — badge·author·text·
    source를 포함한 나머지는 전부 입력 값이고, 나눠진 줄들도 그대로 물려받는다.
    badge를 모델이 못 바꾸는 이유: 격하는 제약 완화(가드레일 4)이고, 격상도 사유 텍스트에 섞인
    지시문이 다른 사람 줄을 required로 올리는 통로가 된다. 줄 사이가 섞이지 않게 줄 단위로만 합친다.

    응답은 순서로 합친다 — 개수가 다르거나 index가 위치와 다르면 ValueError다. 결과 text는 항상 입력
    원문이고, 모델이 돌려준 text는 줄이 섞이지 않았는지 보는 확인용이다(NFC·제로폭·공백 제거 후 비교,
    그래도 다르면 지어내거나 섞은 것이라 ValueError).
    반경은 MIN_RADIUS_M~MAX_RADIUS_M 밖이면 무시한다 — 비정상 값은 후보를 전멸시킨다."""
    reasons = output.reasons
    if len(reasons) != len(inputs):
        raise ValueError(f"응답 개수({len(reasons)})가 입력 개수({len(inputs)})와 다르다")

    groups: list[list[EvidenceLine]] = []
    for position, (raw, planned) in enumerate(zip(inputs, reasons)):
        base = EvidenceLine(**raw)
        if planned.index != position:
            raise ValueError(f"응답 index({planned.index})가 위치({position})와 다르다")
        if _normalize(planned.text) != _normalize(base.text):
            raise ValueError("응답 text가 입력 text와 다르다")
        groups.append(_split_reason(base, planned))
    return groups


def passthrough_planner(raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]:
    return [[EvidenceLine(**reason)] for reason in raw_reasons]


# 엘리스 게이트웨이가 비스트리밍 응답을 2000토큰으로 제한한다(#325). 사유 한 줄의 응답(text 에코 + 조건
# 몇 개)이 70토큰 안팎이라 한 호출에 10개씩만 보낸다. 묶음은 순차로 부른다(동시 호출은 상한·429 위험).
PLAN_BATCH_SIZE = 10


def _model_planner(client: Any, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]:
    passthrough_planner(raw_reasons)  # 입력 shape부터 검증 — 깨진 입력으로 모델을 부르지 않는다
    groups: list[list[EvidenceLine]] = []
    for start in range(0, len(raw_reasons), PLAN_BATCH_SIZE):
        batch = raw_reasons[start:start + PLAN_BATCH_SIZE]
        # index는 묶음마다 0부터라 묶음 단위로 합친다. 한 묶음이 실패하면 LlmCallError·ValueError가
        # 그대로 올라간다 — 부분 결과를 지어내지 않는다.
        groups.extend(merge_planned(batch, call_planner(client, batch)))
    return groups


def real_evidence_planner(raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]:
    """LLM_MODE=real의 ② — Luna를 부른다. 클라이언트는 호출 때 만든다(설정이 비면 LlmCallError →
    plan_evidence가 PlanEvidenceFailed로 바꾼다). dev는 passthrough_planner다 — 고르는 곳은 recommend/deps.py."""
    return _model_planner(get_client(), raw_reasons)


def plan_evidence(
    raw_reasons: Sequence[Mapping[str, Any]], *, planner: EvidencePlanner
) -> list[list[EvidenceLine]]:
    """② 사유 → 실격/선호/반경 구조화.

    raw_reasons: recommend가 모은 reaction/manual 원문(EvidenceLine 필드와 동일 shape의 dict).
    반환: 입력 글마다 근거 줄 묶음 하나 — 바깥 리스트는 입력과 개수·순서가 같고(i번째 묶음 = i번째 입력),
    묶음마다 1줄 이상이다. 글 하나에 조건이 여럿이면 묶음 안에 조건마다 줄이 하나씩 있다(#419).
    planner는 호출하는 쪽이 넘긴다(dev=passthrough_planner 검증·통과 스텁, real=real_evidence_planner Luna 호출).
    LLM_MODE로 고르는 일은 recommend/deps.py가 한다(#219).
    호출·검증이 실패하면 PlanEvidenceFailed — 빈 결과로 바꿔 삼키지 않는다.
    """
    if not raw_reasons:
        return []
    try:
        return planner(raw_reasons)
    except (LlmCallError, ValueError) as exc:
        # pydantic.ValidationError는 ValueError의 하위 클래스다(입력 dict가 스키마에 안 맞는 경우 포함).
        # str(exc)는 응답에 넣지 않는다 — ValidationError 문자열에는 입력값(사용자 사유 원문)이 들어 있다(#390).
        cause = exc.__cause__ or exc  # LlmCallError는 원인 예외를 달고 온다 — 응답에는 클래스명만
        log.warning("plan_evidence 실패: %s(%s), 사유 %d개", type(exc).__name__, type(cause).__name__, len(raw_reasons))
        raise PlanEvidenceFailed(f"{type(exc).__name__}({type(cause).__name__}): 사유 구조화에 실패했다") from exc


def label_place(
    place_raw_facts: Mapping[str, Any],
    fact_keys: Sequence[FactKey],
    evidence_by_fact_key: Optional[Mapping[FactKey, str]] = None,
) -> list[PlaceFactLabel]:
    """③-a-1 장소 라벨링 — fact_key마다 confidence(known/unknown) 판정만 반환한다.

    place_raw_facts: docs/architecture.md 3층 모델의 층1·2 원자료(장소 상세, 메뉴, 리뷰 등에서
    이미 수집된 값). 실제 모델 연동 전 v1 스텁은 이 원자료에 해당 fact_key 값이 명시적으로
    있을 때만 known으로 응답하고, 없으면(누락/None) 항상 unknown이다 — 정보가 부족하다고
    값을 지어내지 않는다.

    evidence_by_fact_key: 모델(또는 상위 단계)이 "원자료의 이 부분을 보고 판단했다"고 주장하는
    근거 텍스트. v1 스텁 자체는 evidence를 만들어내지 않지만(주어지지 않으면 항상 None), 이
    인자로 evidence가 들어오면 place_raw_facts의 문자열 값들과 실제로 대조한다 — 평탄화한
    원문 어디에도 부분 문자열로 없으면 근거를 지어낸 것으로 보고 confidence를 unknown으로
    강등하고 value·evidence를 전부 None으로 덮어써서 지어낸 근거가 known으로 새어나가지
    않게 한다.

    반환값은 라벨(판단)일 뿐이다. unknown_policy 적용이나 실격 여부 판단은 하지 않는다
    (recommend의 책임, 가드레일 7).
    """
    evidence_by_fact_key = evidence_by_fact_key or {}
    raw_texts = _flatten_string_values(place_raw_facts)

    labels: list[PlaceFactLabel] = []
    for key in fact_keys:
        value = place_raw_facts.get(key)
        if value is None:
            labels.append(PlaceFactLabel(fact_key=key, confidence="unknown"))
            continue

        evidence = evidence_by_fact_key.get(key)
        if evidence is not None and (
            not evidence.strip() or not any(evidence in text for text in raw_texts)
        ):
            # 공백만 있는 evidence는 근거가 없는 것과 동일하게 취급해 강등한다
            # (pins/core.py validate_reaction이 공백만 있는 reason_text를 처리하는 패턴과 동일) —
            # 그렇지 않으면 evidence=""일 때 "" in text가 항상 True라서 대조가 무력화된다.
            # 원자료 어디에도 없는 근거(지어낸 근거)도 동일하게 강등한다.
            labels.append(PlaceFactLabel(fact_key=key, confidence="unknown"))
            continue

        labels.append(
            PlaceFactLabel(fact_key=key, value=value, confidence="known", evidence=evidence)
        )
    return labels


def rank_candidates(candidate_place_ids: Sequence[str]) -> list[RankedCandidate]:
    """③-b 선호 순위 채점.

    candidate_place_ids: 실격 통과분(recommend가 필터링을 마친 후보)만 들어온다는 전제.
    이 함수는 순위만 매기며 실격 여부는 다시 판단하지 않는다(가드레일 7).
    v1 스텁은 실제 모델 호출 없이 입력 순서를 그대로 순위로 반환하고, 근거가 없으므로
    member_comment는 지어내지 않고 None으로 둔다(5-7-1).
    """
    return [
        RankedCandidate(place_id=place_id, rank=index + 1, member_comment=None)
        for index, place_id in enumerate(candidate_place_ids)
    ]


# ---------- v2 계획 보조 에이전트 (docs/agent-v2.md 7, 10, 11절, #532) ----------
# agent가 백그라운드 관찰에서 부른다. planner는 ②처럼 부르는 쪽이 넘긴다 — 고정 응답 스텁과 실제 모델 중 무엇을 쓸지는
# agent/deps.py의 Gateway가 고른다(명세 2절 7번). 모델 출력 검증(claim 대조, 문장, 행동)은 agent의 core가 하고, 여기서는
# 스키마 검증까지만 한다. 실패하면 재요청하지 않고 AgentCallFailed를 돌려준다(명세 2절 10번).

# agent가 넘기는 도구 실행 콜백: (call_id, 도구 이름, 인자) -> 결과. 결과는 JSON으로 바꿀 수 있는 값이어야 한다.
# 실행, 지도 채우기(map_id), tool_calls 기록은 agent(tools.py, #533)가 한다. call_id는 이 모듈이 t1, t2 … 로 매긴다.
ToolRunner = Callable[[str, str, Mapping[str, Any]], Any]


class ToolCaller(Protocol):
    """planner가 도구를 부르는 창구 — 상한을 지키고 call_id를 매겨 tool_runner로 넘긴다(_ToolBudget)."""

    @property
    def exhausted(self) -> bool: ...

    def __call__(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]: ...


DiagnosisPlanner = Callable[[Mapping[str, Any], ToolCaller], DiagnosisOutput]
AdvicePlanner = Callable[[Mapping[str, Any], ToolCaller], RunAdviceOutput]


class ToolRunnerError(RuntimeError):
    """agent의 tool_runner가 예외를 냈다. 모델 실패가 아니라 agent 쪽 오류라 실패 결과로 바꾸지 않고 그대로 올린다
    (tool_runner의 ValueError가 스키마 실패로 잘못 분류돼 묻히지 않게 감싼다)."""


class _ToolBudget:
    """호출 1회의 도구 상한(명세 10절 — 진단은 DIAGNOSIS_MAX_TOOL_CALLS, 추천 막힘 조언은 ADVICE_MAX_TOOL_CALLS). 넘는 호출과
    허용되지 않은 도구는 tool_runner를 부르지 않고 오류를 결과로 돌려준다 — 모델은 그 결과를 보고 답을 내면 된다. 실행한
    호출만 상한에 센다(오류로 돌려준 호출은 실행하지 않았다)."""

    def __init__(self, allowed: tuple[str, ...], tool_runner: ToolRunner, *, max_calls: int):
        self._allowed = allowed
        self._tool_runner = tool_runner
        self.max_calls = max_calls
        self.used = 0
        self._structure_used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    def __call__(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if name not in self._allowed:
            return {"error": "NOT_FOUND"}
        is_structure = name == "structure_reasons"
        if self.exhausted or (is_structure and self._structure_used >= STRUCTURE_REASONS_MAX_CALLS):
            return {"error": "LIMIT_EXCEEDED"}
        self.used += 1
        self._structure_used += is_structure
        call_id = f"t{self.used}"
        try:
            result = self._tool_runner(call_id, name, dict(args))
        except Exception as exc:
            raise ToolRunnerError(f"tool_runner 실패: {name} {type(exc).__name__}") from exc
        return {"call_id": call_id, "result": result}


def _failed(what: str, exc: Exception, context: str) -> AgentCallFailed:
    """실패를 결과로 바꾼다. detail과 로그에는 예외 클래스명만 쓴다 — str(ValidationError)에는 응답 본문이 들어 있다(#390)."""
    reason = exc.reason if isinstance(exc, LlmCallError) else "invalid_schema"
    cause = exc.__cause__ or exc
    detail = f"{type(exc).__name__}({type(cause).__name__})"
    log.warning("%s 실패: reason=%s %s %s", what, reason, detail, context)
    return AgentCallFailed(reason=reason, detail=detail)


def fixed_diagnosis_planner(diagnosis_input: Mapping[str, Any], call_tool: ToolCaller) -> DiagnosisOutput:
    """고정 응답 스텁 — 도구를 한 번 부르고(get_reasons. 콜백과 call_id 경로를 통합에서 지나가게) 늘 silent로 답한다.
    지어낸 문장이나 숫자가 화면으로 나갈 길이 없다(명세 2절 10번과 같은 쪽). 도구 결과는 보지 않는다."""
    diagnosis = diagnosis_input["diagnosis"]
    if diagnosis == "split":
        pin_id = diagnosis_input.get("pin_id")
        call_tool("get_reasons", {"pin_ids": [pin_id] if pin_id else None, "category": None, "types": None})
    else:
        call_tool("get_reasons", {"pin_ids": None, "category": diagnosis_input.get("category"), "types": None})
    return DiagnosisOutput(
        decision="silent", diagnosis=diagnosis, signal_id=diagnosis_input["signal_id"], claims=[], advice=[], actions=[],
    )


def _assistant_tool_message(message: Any) -> dict[str, Any]:
    """모델의 도구 호출 응답을 다음 요청의 대화에 되돌려 넣을 모양으로."""
    return {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "type": "function",
             "function": {"name": call.function.name, "arguments": call.function.arguments}}
            for call in message.tool_calls
        ],
    }


def _tool_conversation(
    client: Any, *, prompt: str, payload: Mapping[str, Any], tools: list[dict], call_tool: ToolCaller, max_calls: int,
    turn_call: Callable[..., Any],
) -> Any:
    """도구 호출 대화(진단과 추천 막힘 조언이 같이 쓴다). 상한을 다 썼거나 마지막 왕복이면 tool_choice="none"으로 답을
    받는다 — 요청은 많아야 max_calls + 1번이다. "none"인데도 도구를 부르면 실패(call_failed), 도구 인자 JSON이 깨지면
    ValueError(invalid_schema)다. 어떤 실패도 다시 묻지 않는다."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(dict(payload), ensure_ascii=False, default=str)},
    ]
    for turn in range(max_calls + 1):
        tools_open = turn < max_calls and not call_tool.exhausted
        message = turn_call(client, messages, tools=tools, tool_choice="auto" if tools_open else "none", turn=turn)
        if not message.tool_calls:
            return message.parsed
        if not tools_open:
            raise LlmCallError("도구를 닫은 뒤에도 도구를 불렀다")
        messages.append(_assistant_tool_message(message))
        for call in message.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("도구 인자가 객체가 아니다")
            result = call_tool(call.function.name, args)
            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
    raise LlmCallError("도구 왕복 상한을 넘겼다")  # 마지막 왕복은 늘 "none"이라 오지 않는다


def _model_diagnosis_planner(client: Any, diagnosis_input: Mapping[str, Any], call_tool: ToolCaller) -> DiagnosisOutput:
    return _tool_conversation(
        client, prompt=AGENT_DIAGNOSE_PROMPT, payload=diagnosis_input, tools=diagnosis_tools(diagnosis_input["diagnosis"]),
        call_tool=call_tool, max_calls=DIAGNOSIS_MAX_TOOL_CALLS, turn_call=call_agent_diagnosis_turn,
    )


def real_diagnosis_planner(diagnosis_input: Mapping[str, Any], call_tool: ToolCaller) -> DiagnosisOutput:
    """실제 모델(gpt-6-luna, 도구 호출). 클라이언트는 호출 때 만든다 — 설정이 비면 LlmCallError(call_failed)."""
    return _model_diagnosis_planner(get_client(), diagnosis_input, call_tool)


def agent_diagnose(
    diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner, planner: DiagnosisPlanner
) -> AgentReply[DiagnosisOutput]:
    """모델 유형(stall, split) 진단(명세 6.2, 6.3, 11절).

    diagnosis_input: agent의 core.diagnosis_input(#533)이 만든 공개 데이터만의 dict. 적어도 signal_id, diagnosis(stall|split)가
    있고, stall은 category, split은 pin_id가 있다. 모델에는 JSON 문자열로만 넘긴다.
    tool_runner: 도구 실행 콜백. 이 함수가 call_id(t1, t2 …)를 매겨 부른다. 진단 1회당 DIAGNOSIS_MAX_TOOL_CALLS(5)회,
    그중 structure_reasons는 STRUCTURE_REASONS_MAX_CALLS(1)회까지 실행하고, 넘는 호출은 실행하지 않고 LIMIT_EXCEEDED를,
    유형에 허용되지 않은 도구는 NOT_FOUND를 도구 결과로 돌려준다. tool_runner의 예외는 ToolRunnerError로 그대로 올라간다.

    결과(DiagnosisOutput 또는 AgentCallFailed)와 사용량(AgentUsage, #564. 도구 왕복 전부의 합)을 함께 돌려준다. 실패(호출
    실패, 타임아웃, 스키마 검증 실패)는 재요청하지 않고 AgentCallFailed로 돌려준다. signal_id·diagnosis가 입력과 같은지,
    claim과 문장과 행동은 agent의 verify_diagnosis가 본다(명세 11.2)."""
    diagnosis = diagnosis_input["diagnosis"]
    if diagnosis not in DIAGNOSIS_TOOLS:
        raise ValueError(f"진단 유형이 아니다: {diagnosis}")  # agent 쪽 오류 — 모델 실패가 아니다
    budget = _ToolBudget(DIAGNOSIS_TOOLS[diagnosis], tool_runner, max_calls=DIAGNOSIS_MAX_TOOL_CALLS)
    with metering() as usage:
        try:
            output = planner(diagnosis_input, budget)
        except (LlmCallError, ValueError) as exc:
            return AgentReply(_failed("agent_diagnose", exc, f"diagnosis={diagnosis} tools_used={budget.used}"), usage)
    log.info("agent_diagnose 완료: diagnosis=%s decision=%s tools_used=%d", diagnosis, output.decision, budget.used)
    return AgentReply(output, usage)


# ---------- 추천 막힘 조언 (docs/agent-v2.md 9절, 10절, 11절, #587) ----------
# 진단과 같은 길이다: 도구는 agent의 tool_runner로만, 상한은 ADVICE_MAX_TOOL_CALLS, 실패는 AgentCallFailed, 사용량은 AgentReply.
# 도구 목록은 추천 막힘 전용 4개(RUN_ADVICE_TOOLS)이고 structure_reasons는 없다. 검증(종류별 행동, 요청자 본인 줄, 반경 상한)은
# agent의 core가 한다.


def fixed_advice_planner(advice_input: Mapping[str, Any], call_tool: ToolCaller) -> RunAdviceOutput:
    """고정 응답 스텁 — 근거 줄을 한 번 읽고(도구 콜백과 call_id 경로를 통합에서 지나가게) 늘 silent로 답한다. 지어낸
    문장이나 숫자가 화면으로 나갈 길이 없다(명세 2절 10번). silent의 kind는 쓰이지 않아 버튼이 없는 exhausted로 둔다."""
    call_tool("get_run_evidence", {})
    return RunAdviceOutput(decision="silent", kind="exhausted", claims=[], advice=[], actions=[])


def _model_advice_planner(client: Any, advice_input: Mapping[str, Any], call_tool: ToolCaller) -> RunAdviceOutput:
    return _tool_conversation(
        client, prompt=AGENT_ADVISE_RUN_PROMPT, payload=advice_input, tools=run_advice_tools(),
        call_tool=call_tool, max_calls=ADVICE_MAX_TOOL_CALLS, turn_call=call_agent_advice_turn,
    )


def real_advice_planner(advice_input: Mapping[str, Any], call_tool: ToolCaller) -> RunAdviceOutput:
    """실제 모델(gpt-6-luna, 도구 호출, reasoning_effort="none"). 설정이 비면 LlmCallError(call_failed)."""
    return _model_advice_planner(get_client(), advice_input, call_tool)


def agent_advise_run(
    advice_input: Mapping[str, Any], *, tool_runner: ToolRunner, planner: AdvicePlanner
) -> AgentReply[RunAdviceOutput]:
    """추천 막힘 조언(명세 9절). 그 run의 요청자 한 명에게 그 run의 데이터로만 조언한다.

    advice_input: agent의 core.advice_input이 만든 dict(카테고리, 결과 수, 반경 상한, 미리 읽은 깔때기 등). 모델에는 JSON
    문자열로만 넘긴다. 구성원은 "본인"과 "다른 구성원"으로만 들어 있어야 한다(agent 책임).
    tool_runner: 도구 실행 콜백. call_id(t1, t2 …)를 매겨 부른다. 1회당 ADVICE_MAX_TOOL_CALLS(5)회까지 실행하고, 넘는 호출은
    LIMIT_EXCEEDED, 추천 막힘 전용 4개(RUN_ADVICE_TOOLS) 밖의 도구는 NOT_FOUND를 도구 결과로 돌려준다.

    결과(RunAdviceOutput 또는 AgentCallFailed)와 사용량을 함께 돌려준다. 실패는 재요청하지 않는다."""
    budget = _ToolBudget(RUN_ADVICE_TOOLS, tool_runner, max_calls=ADVICE_MAX_TOOL_CALLS)
    with metering() as usage:
        try:
            output = planner(advice_input, budget)
        except (LlmCallError, ValueError) as exc:
            return AgentReply(_failed("agent_advise_run", exc, f"tools_used={budget.used}"), usage)
    log.info("agent_advise_run 완료: decision=%s kind=%s tools_used=%d", output.decision, output.kind, budget.used)
    return AgentReply(output, usage)

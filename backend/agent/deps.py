"""
의존성 배선 — llm 쪽 agent 함수를 실제 모델로 부를지 고정 응답 스텁으로 대신할지 여기서 고른다(docs/agent-v2.md 2절 7번,
recommend/deps.py와 같은 방식). llm은 요청만 받고, 고르는 것은 받는 쪽인 agent다. 고르는 방법은 llm.api 함수에 넘기는
planner다(#532): dev는 fixed planner, real은 real planner.

- diagnose(#533): `llm.api.agent_diagnose`. 결과와 사용량을 `AgentReply(result, usage)`로 돌려준다(#564). 실패는 예외가
  아니라 result의 `AgentCallFailed`로 온다. dev 스텁은 get_reasons를 한 번 부른 뒤 늘 silent다 — 지어낸 문장이나 숫자가
  화면에 나갈 길이 없다(명세 2절 10번). 우선순위는 모델이 아니라 코드 규칙이라(core.fallback_order, #582) 여기 없다.
- structure(#533): structure_reasons 도구가 쓰는 ②(`llm.api.plan_evidence`). dev는 입력을 그대로 돌려주는 스텁이라 글에
  키가 붙지 않는다. 실패는 `PlanEvidenceFailed`(예외)다 — 도구가 오류 결과로 바꾼다.
- summarize: 우리 조건 요약은 고정 문구라(2026-10-16 결정, #586) flows가 부르지 않는다. 맞춤 문장이 필요한지는 #588에서
  다시 본다. real은 부르면 NotImplementedError다.
- advise_run(#587): `llm.api.agent_advise_run`. 진단과 같이 `AgentReply`를 돌려주고 실패는 result의 `AgentCallFailed`다. dev
  스텁은 get_run_evidence를 한 번 부른 뒤 늘 silent다 — 조언은 빈 값으로 저장되고 GET은 204다.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from fastapi import Depends

from agent.schemas import AgentReply, DiagnosisOutput, RunAdviceOutput, SummaryOutput
from common.adapters import select
from common.database import get_db_session
from common.settings import settings
from llm import api as llm_api

# 도구 콜백: (call_id, 도구 이름, 인자) -> 결과. call_id(t1, t2 …)는 llm이 매긴다(#532). 실행과 tool_calls 기록은
# agent(tools.py)가 한다.
ToolRunner = llm_api.ToolRunner


class AgentLlmGateway(Protocol):
    def diagnose(
        self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[DiagnosisOutput]: ...

    def structure(self, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[llm_api.EvidenceLine]]: ...

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput: ...

    def advise_run(
        self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[RunAdviceOutput]: ...


class FixedAgentLlmGateway:
    """고정 응답 스텁 — 모델을 부르지 않는다. llm.api 함수에 fixed planner를 넘겨 오케스트레이션(도구 콜백, 실패 처리)은
    실제와 같은 길로 지나간다."""

    def diagnose(
        self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[DiagnosisOutput]:
        return llm_api.agent_diagnose(diagnosis_input, tool_runner=tool_runner, planner=llm_api.fixed_diagnosis_planner)

    def structure(self, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[llm_api.EvidenceLine]]:
        return llm_api.plan_evidence(raw_reasons, planner=llm_api.passthrough_planner)

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput:
        return SummaryOutput(decision="silent", claims=[], requests=[])

    def advise_run(
        self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[RunAdviceOutput]:
        return llm_api.agent_advise_run(advice_input, tool_runner=tool_runner, planner=llm_api.fixed_advice_planner)


class RealAgentLlmGateway:
    """실제 모델(gpt-6-luna). summarize는 고정 문구라 llm 함수가 없다 — 부르면 바로 실패한다(real이라고 떴는데 스텁이 도는
    일이 없게)."""

    def diagnose(
        self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[DiagnosisOutput]:
        return llm_api.agent_diagnose(diagnosis_input, tool_runner=tool_runner, planner=llm_api.real_diagnosis_planner)

    def structure(self, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[llm_api.EvidenceLine]]:
        return llm_api.plan_evidence(raw_reasons, planner=llm_api.real_evidence_planner)

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput:
        raise NotImplementedError("llm.api.agent_summarize가 없다 — 요약 문장은 고정 문구다(2026-10-16, #588에서 재검토)")

    def advise_run(
        self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[RunAdviceOutput]:
        return llm_api.agent_advise_run(advice_input, tool_runner=tool_runner, planner=llm_api.real_advice_planner)


def _fixed_agent_llm_gateway() -> AgentLlmGateway:
    return FixedAgentLlmGateway()


def _real_agent_llm_gateway() -> AgentLlmGateway:
    return RealAgentLlmGateway()


get_llm_gateway = select(
    "agent.LlmGateway", settings.llm_mode,
    {"dev": _fixed_agent_llm_gateway, "real": _real_agent_llm_gateway}, "#532",
)


DbSession = Depends(get_db_session)
LlmGatewayDep = Depends(get_llm_gateway)

"""
의존성 배선 — llm 쪽 agent 함수를 실제 모델로 부를지 고정 응답 스텁으로 대신할지 여기서 고른다(docs/agent-v2.md 2절 7번,
recommend/deps.py와 같은 방식). llm은 요청만 받고, 고르는 것은 받는 쪽인 agent다.

**M0(#513) 상태**: llm에 agent 함수(agent_prioritize, agent_diagnose, agent_summarize, agent_advise_run)가 아직 없다(M1).
그래서 `AgentLlmGateway`라는 자리와 고정 응답 스텁만 두고 llm을 import하지 않는다.

- 스텁은 모델을 부르지 않는다. 우선순위는 받은 순서 그대로, 나머지는 전부 silent다. 지어낸 문장이나 숫자가 화면에
  나갈 길이 없다(명세 2절 10번 "검증 실패면 침묵"과 같은 쪽으로 기운다).
- 아직 `common.adapters.select`로 고르지 않는다. M0은 모델을 부르지 않는 shadow라(명세 1절, 18절) 고를 real 구현이
  없고, main.py가 agent를 import하지 않는 동안 포트를 등록하면 등록 여부가 테스트 순서에 따라 달라진다
  (common/tests/test_adapter_assembly.py). M1에서 router를 main.py에 올리고 llm.api의 agent 함수를 부르는
  `RealAgentLlmGateway`를 만들 때 recommend/deps.py처럼 `select("agent.LlmGateway", settings.llm_mode, ...)`로 바꾼다.
- 입력 모양(`core.diagnosis_input` 등)은 #514·M1에서 정해진다. 그때 Mapping을 구체 타입으로 바꾼다.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from fastapi import Depends

from agent.schemas import DiagnosisOutput, PriorityItem, PriorityOutput, RunAdviceOutput, SummaryOutput

# 도구 콜백: (도구 이름, 인자) -> 결과. agent가 llm에 넘기고, 실행과 tool_calls 기록은 agent(tools.py, M1)가 한다.
ToolRunner = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class AgentLlmGateway(Protocol):
    def prioritize(self, signals: Sequence[Mapping[str, Any]], principles: Sequence[str]) -> PriorityOutput: ...

    def diagnose(self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> DiagnosisOutput: ...

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput: ...

    def advise_run(self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> RunAdviceOutput: ...


class FixedAgentLlmGateway:
    """고정 응답 스텁 — 모델을 부르지 않고 도구도 쓰지 않는다. 출력은 스키마 검증을 통과하는 최소 응답이다."""

    def prioritize(self, signals: Sequence[Mapping[str, Any]], principles: Sequence[str]) -> PriorityOutput:
        return PriorityOutput(order=[PriorityItem(signal_id=s["id"], reason="고정 응답") for s in signals])

    def diagnose(self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> DiagnosisOutput:
        return DiagnosisOutput(
            decision="silent", diagnosis=diagnosis_input["diagnosis"], signal_id=diagnosis_input["signal_id"],
            claims=[], advice=[], actions=[],
        )

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput:
        return SummaryOutput(decision="silent", claims=[], requests=[])

    def advise_run(self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> RunAdviceOutput:
        # silent이면 kind는 쓰이지 않는다. 스키마가 값을 요구해서 행동이 없는 exhausted를 넣는다
        return RunAdviceOutput(decision="silent", kind="exhausted", claims=[], advice=[], actions=[])


def get_llm_gateway() -> AgentLlmGateway:
    """M0은 LLM_MODE와 무관하게 고정 응답 스텁이다. M1에서 select()로 바꾼다(머리말)."""
    return FixedAgentLlmGateway()


LlmGatewayDep = Depends(get_llm_gateway)

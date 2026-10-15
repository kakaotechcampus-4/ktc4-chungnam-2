"""
의존성 배선 — llm 쪽 agent 함수를 실제 모델로 부를지 고정 응답 스텁으로 대신할지 여기서 고른다(docs/agent-v2.md 2절 7번,
recommend/deps.py와 같은 방식). llm은 요청만 받고, 고르는 것은 받는 쪽인 agent다.

**M1-1(#531) 상태**: `select("agent.LlmGateway", settings.llm_mode, ...)`로 등록한다(#513에서 미룬 것). router.py가
이 파일을 import하므로 main.py가 뜰 때 포트가 기동 로그(format_assembly)에 오른다.

- dev: 고정 응답 스텁. 모델을 부르지 않는다. 우선순위는 받은 순서 그대로, 나머지는 전부 silent다. 지어낸 문장이나
  숫자가 화면에 나갈 길이 없다(명세 2절 10번 "검증 실패면 침묵"과 같은 쪽으로 기운다).
- real: llm.api의 agent 함수(agent_prioritize, agent_diagnose …)를 부를 자리다. 그 함수는 #532에서 생긴다. 그 전까지
  부르면 NotImplementedError다. `real`을 None으로 두지 않은 이유: 로컬 .env가 LLM_MODE=real(② 실제 모델)이면
  select()가 import 시점에 ConfigError를 내 서버가 뜨지 않는다. M1-1의 관찰과 화면 요청은 Gateway를 부르지 않는다
  (코드 유형만 내고 모델 유형은 모델 단계를 건너뛴다).
- 입력 모양(`core.diagnosis_input` 등)은 M1-2(#533)에서 정해진다. 그때 Mapping을 구체 타입으로 바꾼다.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from fastapi import Depends

from agent.schemas import DiagnosisOutput, PriorityItem, PriorityOutput, RunAdviceOutput, SummaryOutput
from common.adapters import select
from common.database import get_db_session
from common.settings import settings

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


class RealAgentLlmGateway:
    """llm.api의 agent 함수로 실제 모델을 부를 자리(#532). 함수가 생기기 전에는 부르면 바로 실패한다 — 고정 응답으로
    조용히 대신하지 않는다(real이라고 떴는데 스텁이 도는 일이 없게)."""

    def _missing(self):
        raise NotImplementedError("llm.api의 agent 함수가 아직 없다(#532)")

    def prioritize(self, signals: Sequence[Mapping[str, Any]], principles: Sequence[str]) -> PriorityOutput:
        self._missing()

    def diagnose(self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> DiagnosisOutput:
        self._missing()

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput:
        self._missing()

    def advise_run(self, advice_input: Mapping[str, Any], *, tool_runner: ToolRunner) -> RunAdviceOutput:
        self._missing()


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

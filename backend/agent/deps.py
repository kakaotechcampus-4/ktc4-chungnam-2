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
- 추천 막힘 조언(#587)은 종류, 문장, 버튼을 코드가 정해(#750) 모델 함수가 없다.
- status(#1168): 지도 현황 문단(`llm.api.agent_status`, 명세 8.2). 입력은 core.status_cells의 칸뿐이다. 결과와 사용량을
  `AgentReply(result, usage)`로 돌려준다. dev 스텁은 칸에서 어긋나지 않는 상태와 숫자 없는 고정 문구를 낸다 — 검증을 늘 통과해
  저장·응답 경로를 dev에서도 지나간다.
- web_check(#1216): 웹 확인(`llm.api.web_check`, 명세 6.8). 입력은 장소 이름, 동네, 특징 이름과 금지 표현 목록(agent.core)뿐이다.
  예산 확인은 llm이 한다. 결과는 `WebCheckResult`(found|not_found|paused|failed)이고 실패도 예외가 아니다. dev 스텁은 웹을 찾지 않아
  늘 failed다 — 칸도 저장도 없고, 찾아보지 않은 dev에서 「찾지 못했어요」라고 말하지 않는다(#1221). 예산을 넘으면 dev에서도 paused다.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from fastapi import Depends
from sqlalchemy.orm import Session

from agent.schemas import AgentReply, DiagnosisOutput, StatusOutput, SummaryOutput
from common.adapters import select
from common.database import SessionLocal, get_db_session
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

    def status(self, status_input: Mapping[str, Any]) -> AgentReply[StatusOutput]: ...

    def web_check(
        self, *, place_name: str, area: str | None, feature: str, forbidden: Sequence[str],
    ) -> llm_api.WebCheckResult: ...


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

    def status(self, status_input: Mapping[str, Any]) -> AgentReply[StatusOutput]:
        return llm_api.agent_status(status_input, planner=llm_api.fixed_status_planner)

    def web_check(
        self, *, place_name: str, area: str | None, feature: str, forbidden: Sequence[str],
    ) -> llm_api.WebCheckResult:
        return llm_api.web_check(place_name=place_name, area=area, feature=feature, forbidden=forbidden,
                                 planner=llm_api.fixed_web_check_planner)


class RealAgentLlmGateway:
    """실제 모델(gpt-6-luna). summarize는 고정 문구라 llm 함수가 없다 — 부르면 바로 실패한다(real이라고 떴는데 스텁이 도는
    일이 없게)."""

    def diagnose(
        self, diagnosis_input: Mapping[str, Any], *, tool_runner: ToolRunner,
    ) -> AgentReply[DiagnosisOutput]:
        return llm_api.agent_diagnose(diagnosis_input, tool_runner=tool_runner, planner=llm_api.real_diagnosis_planner)

    def structure(self, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[llm_api.EvidenceLine]]:
        return llm_api.plan_evidence(raw_reasons, planner=llm_api.real_evidence_planner)

    def status(self, status_input: Mapping[str, Any]) -> AgentReply[StatusOutput]:
        return llm_api.agent_status(status_input, planner=llm_api.real_status_planner)

    def web_check(
        self, *, place_name: str, area: str | None, feature: str, forbidden: Sequence[str],
    ) -> llm_api.WebCheckResult:
        return llm_api.web_check(place_name=place_name, area=area, feature=feature, forbidden=forbidden,
                                 planner=llm_api.real_web_check_planner)

    def summarize(self, summary_input: Mapping[str, Any]) -> SummaryOutput:
        raise NotImplementedError("llm.api.agent_summarize가 없다 — 요약 문장은 고정 문구다(2026-10-16, #588에서 재검토)")


def _fixed_agent_llm_gateway() -> AgentLlmGateway:
    return FixedAgentLlmGateway()


def _real_agent_llm_gateway() -> AgentLlmGateway:
    return RealAgentLlmGateway()


get_llm_gateway = select(
    "agent.LlmGateway", settings.llm_mode,
    {"dev": _fixed_agent_llm_gateway, "real": _real_agent_llm_gateway}, "#532",
)


def get_session_factory() -> Callable[[], Session]:
    """요청 단위 세션(get_db) 대신 짧은 세션을 여러 번 여는 엔드포인트가 쓴다 — `GET /runs/{runId}/advice`는 조회와 저장을
    나눠 연다(docs/agent-v2.md 9절, #587). 테스트는 이 의존성을 테스트 DB로 바꾼다."""
    return SessionLocal


DbSession = Depends(get_db_session)
LlmGatewayDep = Depends(get_llm_gateway)
SessionFactoryDep = Depends(get_session_factory)

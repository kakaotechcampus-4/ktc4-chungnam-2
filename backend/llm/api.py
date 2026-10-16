"""llm 모듈이 다른 모듈에 여는 공개 함수 — 다른 모듈은 service.py 대신 여기서만 가져간다(docs/architecture.md 1절).

- recommend: ②(사유 구조화) plan_evidence. ③-a-1·③-b는 v1 요청 중에 부르지 않는다.
- agent(v2 계획 보조 에이전트, #532): agent_prioritize(신호 순위), agent_diagnose(stall·split 진단, 도구 콜백). 요청 밖
  백그라운드 관찰에서 부른다. 실패는 재요청하지 않고 AgentCallFailed로 돌려준다(docs/agent-v2.md 2절 10번).
  둘 다 AgentReply(result, usage)를 돌려준다 — usage(AgentUsage)는 agent_runs의 model, prompt_version, tokens_in/out(#564).
  DIAGNOSIS_TOOLS(진단 유형 → 허용 도구 이름)는 agent의 tool_runner가 한 번 더 막을 때 쓴다(#564).
  agent_summarize·agent_advise_run은 M2에서 연다.

고정 응답 스텁(dev)과 실제 모델(real) 중 무엇을 쓸지는 이 모듈이 아니라 받는 쪽의 Gateway(recommend/deps.py,
agent/deps.py)가 planner 인자로 고른다.
"""

from llm.prompts import DIAGNOSIS_TOOLS
from llm.schemas import AgentCallFailed, AgentReply, AgentUsage, DiagnosisOutput, EvidenceLine, PriorityOutput
from llm.service import (
    DiagnosisPlanner,
    EvidencePlanner,
    PlanEvidenceFailed,
    PriorityPlanner,
    ToolCaller,
    ToolRunner,
    ToolRunnerError,
    agent_diagnose,
    agent_prioritize,
    fixed_diagnosis_planner,
    fixed_priority_planner,
    passthrough_planner,
    plan_evidence,
    real_diagnosis_planner,
    real_evidence_planner,
    real_priority_planner,
)

__all__ = [
    "EvidenceLine", "EvidencePlanner", "PlanEvidenceFailed",
    "passthrough_planner", "plan_evidence", "real_evidence_planner",
    "AgentCallFailed", "AgentReply", "AgentUsage", "DiagnosisOutput", "PriorityOutput", "DIAGNOSIS_TOOLS",
    "DiagnosisPlanner", "PriorityPlanner", "ToolCaller", "ToolRunner", "ToolRunnerError",
    "agent_diagnose", "agent_prioritize",
    "fixed_diagnosis_planner", "fixed_priority_planner", "real_diagnosis_planner", "real_priority_planner",
]

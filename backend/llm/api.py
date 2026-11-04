"""llm 모듈이 다른 모듈에 여는 공개 함수 — 다른 모듈은 service.py 대신 여기서만 가져간다(docs/architecture.md 1절).

- recommend: ②(사유 구조화) plan_evidence. ③-a-1은 v1 요청 중에 부르지 않고, ③-b 선호 순위는 코드로 옮겼다(#99).
- agent(v2 계획 보조 에이전트, #532): agent_diagnose(stall·split 진단, 도구 콜백). 요청 밖 백그라운드 관찰에서 부른다.
  실패는 재요청하지 않고 AgentCallFailed로 돌려준다(docs/agent-v2.md 2절 10번).
  AgentReply(result, usage)를 돌려준다 — usage(AgentUsage)는 agent_runs의 model, prompt_version, tokens_in/out(#564).
  DIAGNOSIS_TOOLS(진단 유형 → 허용 도구 이름)는 agent의 tool_runner가 한 번 더 막을 때 쓴다(#564).
  신호 순위(agent_prioritize)는 #582에서 지웠다 — agent의 코드 규칙(core.fallback_order)이다.
  요약의 구체화 문장은 고정 문구라 모델 함수가 없다(2026-10-16, #588에서 재검토).
  agent_status(지도 현황 문단, #1168, agent-v2 8.2): 코드가 센 칸을 받아 카테고리별 상태와 문단(StatusOutput)을 낸다. 도구 없음.
  관찰 끝에서 칸이 바뀔 때만 부른다. 검증(core.verify_status)은 agent가 한다. 실패는 AgentCallFailed.
  web_check(웹 확인, #1216, agent-v2 6.8): 장소 이름·동네·특징 이름만 받아 Responses API의 web_search로 찾고, 출처가 그 호출의 검색
  결과에 있는지·http(s)·금지 표현·길이를 검증한 문장 1~2개를 WebCheckResult(found|not_found|paused|failed)로 돌려준다. 서비스 일일
  예산(LLM_DAILY_BUDGET_KRW, 그날 llm_calls 비용 합계)을 보는 곳은 여기 하나다 — 넘으면 부르지 않고 paused. 금지 표현은 부르는 쪽이
  forbidden으로 넘긴다(목록의 정본은 agent.core). 실패는 예외가 아니라 failed다.
- agent.course(v2 동선 에이전트, #334): agent_course_turn(턴 하나 → 다음 행동, CourseTurn), course_set_goals(요청 한 줄 → 목표),
  course_direct_turn(지휘 턴). 실패는 AgentCallFailed.
  점검(review) 판단(#1326): 입력에 `review: {"problems": [{alias, kind, strength, options: [{no, moved, solves, remaining}]}]}`를 담아
  course_direct_turn을 부르면 모델은 action.tool="review"(order, verdicts, picks)로 답한다. 새 호출이 아니라 지휘 턴 한 번이다(상한 그대로).
  verify_course_review(review["…"], call)가 입력과 대조해 CourseReviewDecision(order, worth, picks)을 낸다 — 하드 문제와 입력에 없는
  별칭, 입력과 모순되는 이유는 버린다. 비면 코드 기본(입력 순서, 모두 고침). review.review의 order·worth 훅에 연결하는 것은 agent/course 몫.

고정 응답 스텁(dev)과 실제 모델(real) 중 무엇을 쓸지는 이 모듈이 아니라 받는 쪽의 Gateway(recommend/deps.py,
agent/deps.py)가 planner 인자로 고른다.

사용량 기록(#870): 모델 호출 1건마다 llm_calls 한 행이 남는다. 부르는 쪽은 호출을 `usage_context(feature, map_id=, user_id=, run_id=)`로
감싼다 — feature는 llm.models.FEATURES 중 하나, user_id는 사용자가 부른 호출에만 넣는다. 감싸지 않은 호출은 기록되지 않는다.
- 탈퇴(auth의 WITHDRAW_STEPS): anonymize_by_user — 행은 남기고 user_id만 비운다(비용 통계).
- 게스트 합치기(auth의 MERGE_STEPS): reassign_user.
- 보존: purge_old(30일, maintenance가 부른다).
- 버려진 비용(#848): ② 묶음 중 일부가 실패하거나 누적 시간 상한(PLAN_TOTAL_BUDGET_SECONDS)을 넘으면 그 trace의 성공 호출을 discarded로
  표시한다(llm이 한다). 모델 뒤에 run·근거 저장이 실패한 경우는 부르는 쪽이 `mark_discarded(label.trace_id)`로 표시한다. 호출마다
  batch_size(② 묶음 크기)가 남아 묶음 수는 trace당 plan_evidence 행 수다.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from llm import usage as _usage
from llm.prompts import DIAGNOSIS_TOOLS, PLAN_EVIDENCE_PROMPT
from llm.schemas import (
    AgentCallFailed, AgentReply, AgentUsage, CourseDirectTurn, CourseReviewCall, CourseGoalSet, CourseTurn, DiagnosisOutput, EvidenceLine,
    PlanningOutput, StatusCategory, StatusOutput, VerifiedStatement, WebAnswer, WebCheckOutput, WebCheckResult,
)
from llm.service import (
    CourseDirectPlanner,
    CourseGoalsPlanner,
    CourseTurnPlanner,
    DiagnosisPlanner,
    EvidencePlanner,
    PlanEvidenceFailed,
    ToolCaller,
    ToolRunner,
    StatusPlanner,
    ToolRunnerError,
    WebCheckPlanner,
    fixed_web_check_planner,
    real_web_check_planner,
    source_name,
    verify_web_answer,
    web_check,
    agent_course_turn,
    agent_status,
    CourseReviewDecision,
    course_direct_turn,
    verify_course_review,
    course_set_goals,
    fixed_course_goals_planner,
    real_course_direct_planner,
    real_course_goals_planner,
    agent_diagnose,
    fixed_diagnosis_planner,
    fixed_status_planner,
    passthrough_planner,
    plan_deadline,
    plan_evidence,
    real_course_turn_planner,
    real_diagnosis_planner,
    real_evidence_planner,
    real_status_planner,
)

__all__ = [
    "EvidenceLine", "EvidencePlanner", "PlanEvidenceFailed", "plan_evidence_rules_version",
    "passthrough_planner", "plan_evidence", "real_evidence_planner",
    "AgentCallFailed", "AgentReply", "AgentUsage", "DiagnosisOutput", "DIAGNOSIS_TOOLS",
    "DiagnosisPlanner", "ToolCaller", "ToolRunner", "ToolRunnerError",
    "agent_diagnose", "fixed_diagnosis_planner", "real_diagnosis_planner",
    "StatusCategory", "StatusOutput", "StatusPlanner", "agent_status", "fixed_status_planner", "real_status_planner",
    "WebCheckResult", "VerifiedStatement", "WebAnswer", "WebCheckOutput", "WebCheckPlanner", "web_check",
    "fixed_web_check_planner", "real_web_check_planner", "verify_web_answer", "source_name",
    "CourseTurn", "CourseTurnPlanner", "agent_course_turn", "real_course_turn_planner",
    "CourseGoalSet", "CourseGoalsPlanner", "course_set_goals", "fixed_course_goals_planner", "real_course_goals_planner",
    "CourseDirectTurn", "CourseDirectPlanner", "course_direct_turn", "real_course_direct_planner",
    "CourseReviewCall", "CourseReviewDecision", "verify_course_review",
    "usage_context", "mark_discarded", "plan_deadline", "anonymize_by_user", "reassign_user", "purge_old",
]

def plan_evidence_rules_version() -> str:
    """② 사유 구조화 규칙의 버전(#1095) — 프롬프트 글과 응답 스키마의 해시 앞 12자리(16진). 둘 중 하나라도 바뀌면 값이 달라진다.
    손으로 올리는 번호가 아니라 잊을 수 없다. agent가 우리 조건 요약에 이 값을 남겨 ② 규칙이 바뀌면 요약을 다시 만든다.
    순수 함수이고 모델을 부르지 않는다."""
    schema = json.dumps(PlanningOutput.model_json_schema(), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256((PLAN_EVIDENCE_PROMPT + "\n" + schema).encode("utf-8")).hexdigest()
    return digest[:12]


usage_context = _usage.usage_context
mark_discarded = _usage.mark_discarded   # 모델은 불렸는데 결과가 저장되지 않은 호출을 표시한다(#848). trace_id는 usage_context가 준 라벨의 것


def anonymize_by_user(db: Session, *, user_id: str) -> int:
    """계정 탈퇴가 부른다 — 그 사람의 llm_calls 행은 남기고 user_id만 비운다(비용 통계는 유지). 바꾼 행 수."""
    return _usage.anonymize_by_user(db, user_id=user_id)


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기가 부른다 — from_user의 llm_calls 행을 to_user로 옮긴다(충돌 없음, 멱등, 커밋은 호출자)."""
    return _usage.reassign_user(db, from_user_id=from_user_id, to_user_id=to_user_id)


def purge_old(db: Session, *, now: datetime, older_than_days: int = _usage.RETENTION_DAYS) -> dict[str, int]:
    """보존 기간(30일)이 지난 llm_calls 행을 지운다. maintenance.run이 부른다. 테이블 → 지운 행 수."""
    return _usage.purge_old(db, now=now, older_than_days=older_than_days)

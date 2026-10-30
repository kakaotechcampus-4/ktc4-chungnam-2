"""llm 모듈이 소유하는 테이블 1개 — `llm_calls`(마이그레이션 0043, #870).

모델 호출 1건 = 1행이다. 기록은 출구(client.call_planner, client._agent_parse) 한 곳에서 llm.usage가 한다.
- 무엇을 위해 불렀는지(feature), 어느 지도·사람·실행인지(map_id, user_id, run_id)는 부르는 쪽이 `llm.api.usage_context`로 붙인다.
  같은 usage_context 안의 호출은 trace_id가 같다 — run_id가 아직 없는 호출(추천 ②는 run INSERT 전, 진단은 agent_runs INSERT 전)도
  실행 1번 단위로 묶을 수 있다.
- 사유 원문, 요청 원문, 응답 본문은 저장하지 않는다. 숫자와 분류만이다.
- map_id, user_id, run_id는 다른 모듈처럼 문자열이고 FK가 없다. 탈퇴는 user_id만 비우고 행은 남긴다(비용 통계), 게스트 합치기는
  user_id를 옮긴다(api.anonymize_by_user, api.reassign_user). 30일 지난 행은 maintenance가 지운다(api.purge_old).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

# 왜 불렀는지 — 작업 1 조사(#870)의 호출 지점. 사용자 호출과 서버 호출의 비중은 user_id 유무로 가른다.
FEATURES = (
    "recommend_run",    # 추천 실행의 ② (POST /runs)
    "evidence_add",     # 「+」 근거 추가의 ② (PATCH /runs/{id}/evidence)
    "agent_diagnose",   # 관찰의 진단 — 진단 왕복과 그 안의 ②(사전 비교, structure_reasons, compare_reasons)
    "agent_summary",    # 우리 조건 요약의 ②
    "course",           # AI 코스 짜기 — 목표 세우기와 지휘 턴
)
# 무엇을 불렀는지 — client의 호출 함수
CALLS = ("plan_evidence", "agent_diagnose", "course_goals", "course_direct", "course_turn")
OUTCOMES = ("ok", "refusal", "empty", "timeout", "invalid_schema", "call_failed")


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_created", "created_at"),
        Index("ix_llm_calls_map_created", "map_id", "created_at"),
        Index("ix_llm_calls_user_created", "user_id", "created_at"),
        Index("ix_llm_calls_trace", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature: Mapped[str] = mapped_column(String, nullable=False)   # FEATURES
    call: Mapped[str] = mapped_column(String, nullable=False)      # CALLS
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    map_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)   # 서버가 부른 호출은 None
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # 캐시 입력과 캐시 쓰기 할증(cache_write_tokens의 25%, 게이트웨이가 더해 보고한다) 포함
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")   # 캐시 미스로 새로 쓴 몫
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")   # 추론 토큰 포함
    cost_krw: Mapped[float] = mapped_column(Numeric(12, 4, asdecimal=False), nullable=False, default=0, server_default="0")
    outcome: Mapped[str] = mapped_column(String, nullable=False)   # OUTCOMES
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

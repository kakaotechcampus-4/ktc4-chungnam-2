"""
agent 모듈이 소유하는 테이블 7개 — docs/data-model.md agent 절과 docs/agent-v2.md 13절이 정본이다(마이그레이션 0029).

- `map_id`는 다른 모듈처럼 문자열이고 FK를 걸지 않는다(maps FK 미결과 같은 이유). `agent_run_advice.run_id`도
  recommend_runs.id지만 모듈 경계라 FK가 없다.
- 상태값(trigger, outcome, diagnosis, status)은 명세대로 text다. 허용 값은 아래 튜플에 적어 두고 쓰는 쪽이 지킨다.
- 지도 정리는 `api.purge_map_data`, 탈퇴는 `api.delete_by_user`가 이 테이블들을 지운다(명세 12.9).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

RUN_TRIGGERS = ("activity", "time", "summary", "run_advice")
RUN_OUTCOMES = (
    "no_signal", "blocked", "silent", "unknown", "invalid_schema", "invalid_claims",
    "stale", "suggested", "summarized", "advised", "trip_ended", "map_deleted",
)
DIAGNOSES = ("stall", "split", "no_reaction", "category_gap")
SUGGESTION_STATUSES = ("active", "accepted", "dismissed", "expired", "superseded")

_EMPTY_JSON_LIST = text("'[]'::jsonb")


class AgentSettings(Base):
    """지도별 모드. 행이 없으면 켜짐(기본값)."""

    __tablename__ = "agent_settings"

    map_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentCursor(Base):
    """책갈피, 다음 시간 점검 시각, 중복 실행 방지 자리표. 관찰 흐름만 쓴다(명세 12.5).
    last_seen_seq는 본 것 중 가장 큰 event_log seq다(#525) — 구멍은 추적하지 않는다(gap_seq는 0030에서 지웠다)."""

    __tablename__ = "agent_cursors"

    map_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRun(Base):
    """관찰 한 번의 기록. 침묵으로 끝난 관찰도 남긴다. 30일 보존.

    `tool_calls`와 `verification`에는 사유 원문이 들어갈 수 있다 — 탈퇴 때 `api.delete_by_user`가 비운다."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_map_started", "map_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)  # RUN_TRIGGERS
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    signals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_JSON_LIST)
    blocked: Mapped[list] = mapped_column(  # [{signal_id, reason}]
        JSONB, nullable=False, default=list, server_default=_EMPTY_JSON_LIST
    )
    priority: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # model_order, final_order, corrections, reused
    policy_version: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    used_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_JSON_LIST)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # RUN_OUTCOMES
    outcome_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AgentSuggestion(Base):
    """바텀시트에 뜨는 지도 제안. 지도당 active는 하나(부분 유니크 인덱스)."""

    __tablename__ = "agent_suggestions"
    __table_args__ = (
        Index("uq_agent_suggestions_active", "map_id", unique=True, postgresql_where=text("status = 'active'")),
        Index("ix_agent_suggestions_map_fp", "map_id", "fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    diagnosis: Mapped[str] = mapped_column(String, nullable=False)  # DIAGNOSES
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    pin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)  # 슬롯 문장. 렌더는 응답과 이벤트 때(#531)
    claims: Mapped[list] = mapped_column(JSONB, nullable=False)  # 검증 통과분
    analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # split의 충돌 지점 등
    advice: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{slot_text, is_guess}] 슬롯 문장만
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{index, type, label, params}]
    status: Mapped[str] = mapped_column(String, nullable=False)  # SUGGESTION_STATUSES
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)  # 기록만. 화면과 이벤트에 싣지 않는다
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_action: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decided_within_24h: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class AgentSuggestionView(Base):
    """사용자별 열람. 버튼의 점(has_unseen)과 미열람 지표. 첫 열람 시각 = min(viewed_at)."""

    __tablename__ = "agent_suggestion_views"

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_suggestions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentReasonSummary(Base):
    """우리 조건 요약. 카테고리마다 최신본 하나만 덮어쓴다. `summary`에 사유 원문이 들어갈 수 있다."""

    __tablename__ = "agent_reason_summaries"

    map_id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)  # 다섯 칸의 렌더 결과와 근거 reaction_id
    based_on_reaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentRunAdvice(Base):
    """추천 막힘 조언. run당 1행. silent여도 빈 advice로 저장해 다시 만들지 않는다(명세 9절)."""

    __tablename__ = "agent_run_advice"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # recommend_runs.id, FK 없음
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    claims: Mapped[list] = mapped_column(JSONB, nullable=False)
    advice: Mapped[list] = mapped_column(JSONB, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

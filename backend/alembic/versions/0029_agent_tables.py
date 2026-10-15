"""#513 — v2 계획 보조 에이전트 테이블 7개(agent_settings·agent_cursors·agent_runs·agent_suggestions·
agent_suggestion_views·agent_reason_summaries·agent_run_advice).

map_id는 다른 모듈처럼 문자열이고 FK를 걸지 않는다. FK는 agent 안에서만 건다(suggestions → runs SET NULL,
views → suggestions CASCADE). 지도당 활성 제안은 부분 유니크 인덱스 uq_agent_suggestions_active로 하나만 둔다.

docs/data-model.md agent 절, docs/agent-v2.md 13절 참고.

Revision ID: 0029_agent_tables
Revises: 0025_invite_revoke
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_agent_tables"
down_revision: Union[str, None] = "0025_invite_revoke"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPTY_JSON_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("map_id", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_cursors",
        sa.Column("map_id", sa.String(), primary_key=True),
        sa.Column("last_seen_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("gap_seq", sa.BigInteger(), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_seq", sa.BigInteger(), nullable=True),
        sa.Column("signals", postgresql.JSONB(), server_default=EMPTY_JSON_LIST, nullable=False),
        sa.Column("blocked", postgresql.JSONB(), server_default=EMPTY_JSON_LIST, nullable=False),
        sa.Column("priority", postgresql.JSONB(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("used_model", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), server_default=EMPTY_JSON_LIST, nullable=False),
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("outcome_detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_agent_runs_map_started", "agent_runs", ["map_id", "started_at"])

    op.create_table(
        "agent_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("diagnosis", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("pin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("evidence_hash", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("claims", postgresql.JSONB(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("advice", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("shadow", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_action", postgresql.JSONB(), nullable=True),
        sa.Column("decided_within_24h", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "uq_agent_suggestions_active", "agent_suggestions", ["map_id"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_agent_suggestions_map_fp", "agent_suggestions", ["map_id", "fingerprint"])

    op.create_table(
        "agent_suggestion_views",
        sa.Column(
            "suggestion_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_suggestions.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_reason_summaries",
        sa.Column("map_id", sa.String(), primary_key=True),
        sa.Column("category", sa.String(), primary_key=True),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("based_on_reaction_count", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_run_advice",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("claims", postgresql.JSONB(), nullable=False),
        sa.Column("advice", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_run_advice")
    op.drop_table("agent_reason_summaries")
    op.drop_table("agent_suggestion_views")
    op.drop_index("ix_agent_suggestions_map_fp", table_name="agent_suggestions")
    op.drop_index("uq_agent_suggestions_active", table_name="agent_suggestions")
    op.drop_table("agent_suggestions")
    op.drop_index("ix_agent_runs_map_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("agent_cursors")
    op.drop_table("agent_settings")

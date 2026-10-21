"""#334 — AI 코스 짜기(동선 에이전트) run 테이블 1개(agent_course_runs). 팀 결정 #580 전 브랜치 초안.

map_id·requested_by는 FK가 없다(agent 테이블과 같은 관례). 내 진행 중 run은 지도당 하나라 부분 유니크 인덱스
uq_agent_course_runs_active로 막는다. 사유 원문, 장소 이름, 좌표는 저장하지 않는다(models.py 머리말).

docs/data-model.md agent_course_runs 절 참고.

Revision ID: 0037_agent_course_runs
Revises: 0036_ads
Create Date: 2026-10-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_agent_course_runs"
down_revision: Union[str, None] = "0036_ads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "agent_course_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_pin_ids", postgresql.JSONB(), nullable=False),
        sa.Column("goals", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("unmatched", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("excluded", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("steps", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("days", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("violations", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("checks", postgresql.JSONB(), server_default=_EMPTY_LIST, nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_course_runs_map_user", "agent_course_runs", ["map_id", "requested_by", "created_at"])
    op.create_index("ix_agent_course_runs_user_created", "agent_course_runs", ["requested_by", "created_at"])
    op.create_index(
        "uq_agent_course_runs_active", "agent_course_runs", ["map_id", "requested_by"], unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_course_runs_active", table_name="agent_course_runs")
    op.drop_index("ix_agent_course_runs_user_created", table_name="agent_course_runs")
    op.drop_index("ix_agent_course_runs_map_user", table_name="agent_course_runs")
    op.drop_table("agent_course_runs")

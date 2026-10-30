"""#870 — 모델 호출 사용량 테이블 llm_calls(llm 모듈 소유). 호출 1건 = 1행.

map_id·user_id·run_id는 FK가 없다(다른 모듈 테이블과 같은 관례). 사유 원문과 응답 본문은 저장하지 않는다(숫자와 분류만).
탈퇴는 user_id만 비우고, 30일 지난 행은 maintenance가 지운다. docs/data-model.md llm_calls 절 참고.

Revision ID: 0043_llm_calls
Revises: 0042_places_trgm_search
Create Date: 2026-10-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_llm_calls"
down_revision: Union[str, None] = "0042_places_trgm_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("call", sa.String(), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_krw", sa.Numeric(12, 4), server_default="0", nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_calls_created", "llm_calls", ["created_at"])
    op.create_index("ix_llm_calls_map_created", "llm_calls", ["map_id", "created_at"])
    op.create_index("ix_llm_calls_user_created", "llm_calls", ["user_id", "created_at"])
    op.create_index("ix_llm_calls_trace", "llm_calls", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_trace", table_name="llm_calls")
    op.drop_index("ix_llm_calls_user_created", table_name="llm_calls")
    op.drop_index("ix_llm_calls_map_created", table_name="llm_calls")
    op.drop_index("ix_llm_calls_created", table_name="llm_calls")
    op.drop_table("llm_calls")

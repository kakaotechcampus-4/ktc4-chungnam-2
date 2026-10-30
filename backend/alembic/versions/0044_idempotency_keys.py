"""idempotency_keys — 「추천 받기」 연타·재전송을 한 번으로 묶는 키 기록 (#811).

모델 호출 전에 (요청자, 범위, 키)를 독립 트랜잭션으로 INSERT하고, run을 만든 트랜잭션이 run_id를 잇는다.
run_id가 NULL이면 아직 모델을 기다리는 중이다. 처리 기한(90초)이 지나면 새 요청이 이어받아 attempt(세대)를 올린다.
run을 지우면(지도 정리) 키 행도 함께 지운다.

Revision ID: 0044_idempotency_keys
Revises: 0043_llm_calls
Create Date: 2026-10-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_idempotency_keys"
down_revision: Union[str, None] = "0043_llm_calls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recommend_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requested_by", "scope", "key", name="uq_idempotency_keys"),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

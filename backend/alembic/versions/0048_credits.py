"""#948 — 크레딧 테이블 2개(credit_accounts·credit_ledger).

원본은 원장(credit_ledger)이고 credit_accounts.balance는 원장 합을 담아 두는 값이다(행 잠금과 CHECK (balance >= 0) 자리).
ref_id UNIQUE가 멱등을 맡는다. 사용자 id 열에 FK를 걸지 않는다(모듈 경계, #760).

docs/data-model.md credits 절, docs/credits-reviews.md 6절 참고.

Revision ID: 0048_credits
Revises: 0047_agent_cursor_lease_token
Create Date: 2026-11-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048_credits"
down_revision: Union[str, None] = "0047_agent_cursor_lease_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_credit_accounts_balance"),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("ref_id", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_ledger_user_reason_created", "credit_ledger", ["user_id", "reason", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_user_reason_created", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_table("credit_accounts")

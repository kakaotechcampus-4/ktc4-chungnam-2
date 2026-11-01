"""recommend_runs.applied_evidence·last_new_count — 마지막 실행의 근거 스냅샷과 새로 찾은 후보 수 (#845, #847).

둘 다 비어도 된다(expand). 예전 run은 NULL이라 결과 응답이 세 필드(applied_evidence, no_applied_conditions, new_count)를 생략한다.

Revision ID: 0046_run_applied_evidence
Revises: 0045_idempotency_keys
Create Date: 2026-10-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046_run_applied_evidence"
down_revision: Union[str, None] = "0045_idempotency_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recommend_runs", sa.Column("applied_evidence", postgresql.JSONB(), nullable=True))
    op.add_column("recommend_runs", sa.Column("last_new_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommend_runs", "last_new_count")
    op.drop_column("recommend_runs", "applied_evidence")

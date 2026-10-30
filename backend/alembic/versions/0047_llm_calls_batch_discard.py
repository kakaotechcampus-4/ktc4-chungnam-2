"""llm_calls.batch_size·discarded — ② 묶음 크기와 결과가 쓰이지 않은 호출 표시 (#848).

둘 다 비어도 된다(expand). batch_size는 ② 한 호출이 처리한 사유 수(다른 호출은 NULL), discarded는 성공했지만 결과가 쓰이지 않은
호출(뒤 묶음 실패·시간 상한·모델 뒤 저장 실패)이다. 기존 행은 discarded=false.

Revision ID: 0047_llm_calls_batch_discard
Revises: 0046_run_applied_evidence
Create Date: 2026-10-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_llm_calls_batch_discard"
down_revision: Union[str, None] = "0046_run_applied_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("batch_size", sa.Integer(), nullable=True))
    op.add_column("llm_calls", sa.Column("discarded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("llm_calls", "discarded")
    op.drop_column("llm_calls", "batch_size")

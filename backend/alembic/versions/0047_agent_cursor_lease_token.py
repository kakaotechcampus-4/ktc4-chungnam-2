"""agent_cursors.lease_token — 관찰 lease의 주인 표시(fencing token, #812). expand: 비어 있어도 된다.

lease를 잡을 때 새 uuid를 쓰고, 해제·커서 전진·결과 저장은 그 값이 아직 같을 때만 한다.

Revision ID: 0047_agent_cursor_lease_token
Revises: 0046_run_applied_evidence
Create Date: 2026-10-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047_agent_cursor_lease_token"
down_revision: Union[str, None] = "0046_run_applied_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_cursors", sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_cursors", "lease_token")

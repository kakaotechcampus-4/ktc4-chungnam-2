"""#515 — agent_cursors.gap_seq를 지운다.

커서를 "본 것 중 가장 큰 seq"로 바꿔서(docs/agent-v2.md 12.5 개정, #525) 구멍을 추적하지 않는다. 0029에서 만든
칸이고 쓴 적이 없어 옮길 값이 없다. 내리면 빈 칸으로 다시 만든다.

Revision ID: 0030_agent_cursor_drop_gap_seq
Revises: 0029_agent_tables
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_agent_cursor_drop_gap_seq"
down_revision: Union[str, None] = "0029_agent_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("agent_cursors", "gap_seq")


def downgrade() -> None:
    op.add_column("agent_cursors", sa.Column("gap_seq", sa.BigInteger(), nullable=True))

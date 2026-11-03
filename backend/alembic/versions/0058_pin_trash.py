"""pins.deleted_by, pins.deleted_was_confirmed — 핀 휴지통(#1013, 상위 #864).

삭제는 휴지통으로 옮기는 것이다: 핀 행은 30일 남고(deleted_at) 삭제한 사람과 삭제 때 확정이었는지를 함께 기억한다.
둘 다 nullable 새 칸이라 기존 행은 그대로다(expand) — 옛 삭제 행은 NULL이고 복구 때 확정이 아니었던 것으로 본다.
정리(purge_deleted_pins)가 deleted_at으로 오래된 행부터 찾으므로 삭제된 행만 담는 부분 인덱스를 둔다.

Revision ID: 0058_pin_trash
Revises: 0057_agent_advice_state_key
Create Date: 2026-11-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_pin_trash"
down_revision: Union[str, None] = "0057_agent_advice_state_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pins", sa.Column("deleted_by", sa.String(), nullable=True))
    op.add_column("pins", sa.Column("deleted_was_confirmed", sa.Boolean(), nullable=True))
    op.create_index("ix_pins_deleted_at", "pins", ["deleted_at"], postgresql_where=sa.text("deleted_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_pins_deleted_at", table_name="pins")
    op.drop_column("pins", "deleted_was_confirmed")
    op.drop_column("pins", "deleted_by")

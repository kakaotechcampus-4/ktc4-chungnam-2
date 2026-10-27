"""#470 — 앱 안 알림함 테이블 2개(notifications, notification_prefs).

map_id·pin_id에 FK를 걸지 않는다(지도가 삭제돼도 알림은 남는다). docs/data-model.md notifications 절 참고.

Revision ID: 0031_notifications
Revises: 0030_agent_cursor_drop_gap_seq
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_notifications"
down_revision: Union[str, None] = "0030_agent_cursor_drop_gap_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("map_title", sa.String(), nullable=True),
        sa.Column("pin_id", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id"], postgresql_where=sa.text("read_at IS NULL")
    )

    op.create_table(
        "notification_prefs",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_prefs")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")

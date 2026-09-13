"""common 모듈 이벤트 아웃박스 — event_log 테이블

상태 변경과 같은 트랜잭션에 이벤트 행을 남기고(common/events.py record_event), 실제 전달은
realtime이 커밋된 이 테이블을 읽어 재시도하는 형태로 한다(docs/events.md 「전달 보장」).

Revision ID: 0002_event_log
Revises: 0001_pins
Create Date: 2026-09-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_event_log"
down_revision: Union[str, None] = "0001_pins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

event_channel = postgresql.ENUM("public", "private", name="event_channel", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    event_channel.create(bind, checkfirst=True)

    op.create_table(
        "event_log",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("map_id", sa.String(), nullable=False),
        sa.Column("channel", event_channel, nullable=False),
        sa.Column("recipient_user_id", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(channel = 'private') = (recipient_user_id IS NOT NULL)",
            name="ck_event_log_private_recipient",
        ),
    )
    op.create_index("ix_event_log_map_seq", "event_log", ["map_id", "seq"])
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_event_log_created_at", table_name="event_log")
    op.drop_index("ix_event_log_map_seq", table_name="event_log")
    op.drop_table("event_log")

    bind = op.get_bind()
    event_channel.drop(bind, checkfirst=True)

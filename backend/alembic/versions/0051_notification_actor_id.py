"""#857 — notifications.actor_id(nullable) 추가. 탈퇴 7일 뒤 정리가 다른 구성원 알림 문장의 행위자 이름을 덮을 때 쓴다.

FK 없음(다른 사용자 포인터는 문자열, 기존 관례). 응답에는 싣지 않는다. 이미 쌓인 행은 NULL이다.

Revision ID: 0051_notification_actor_id
Revises: 0050_drop_course_user_index
Create Date: 2026-11-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_notification_actor_id"
down_revision: Union[str, None] = "0050_drop_course_user_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("actor_id", sa.String(), nullable=True))
    op.create_index(
        "ix_notifications_actor", "notifications", ["actor_id"], postgresql_where=sa.text("actor_id IS NOT NULL")
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_actor", table_name="notifications")
    op.drop_column("notifications", "actor_id")

"""#10 — 서비스 피드백 테이블 feedback.

user_id는 FK 없이 NULL 허용이다(탈퇴하면 NULL로 끊고 내용은 남긴다). map_id도 FK 없이 검사 없이 저장한다.
docs/data-model.md notifications / feedback 절 참고.

Revision ID: 0032_feedback
Revises: 0031_notifications
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_feedback"
down_revision: Union[str, None] = "0031_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("map_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_table("feedback")

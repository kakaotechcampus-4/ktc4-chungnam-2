"""place_hours — 영업시간·휴무일(v2, #690, 2026-10-24).

장소당 한 행. 칸이 없으면 행이 없다 = 모름(지어내지 않는다). docs/data-model.md place_hours 절 참고.

Revision ID: 0038_place_hours
Revises: 0037_agent_course_runs
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_place_hours"
down_revision: Union[str, None] = "0037_agent_course_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "place_hours",
        sa.Column("place_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("places.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("hours", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("closed_days", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("closed_note", sa.Text(), nullable=True),
        sa.Column("hours_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("place_hours")

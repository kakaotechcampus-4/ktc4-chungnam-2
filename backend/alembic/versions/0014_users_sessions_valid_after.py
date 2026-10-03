"""users.sessions_valid_after 추가 — 로그아웃이 이 시각을 갱신해 이미 발급된(복사된 포함)
세션 토큰을 무효화한다. nullable: 로그아웃 이력이 없는 기존 사용자는 NULL(=모두 유효).

Revision ID: 0014_users_sessions_valid_after
Revises: 0013_regions_anchor_points
Create Date: 2026-09-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_users_sessions_valid_after"
down_revision: Union[str, None] = "0013_regions_anchor_points"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sessions_valid_after")

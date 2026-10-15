"""users 게스트 열 추가(#472) — is_guest(기본 false), guest_invite_token(초대 토큰당 10명 셈, 인덱스), last_seen_at.

provider는 enum이 아니라 text라 'guest' 값 추가에 DDL이 필요 없다(값 제약은 서비스 계층).

Revision ID: 0035_users_guest
Revises: 0034_places_curated
Create Date: 2026-10-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_users_guest"
down_revision: Union[str, None] = "0034_places_curated"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("guest_invite_token", sa.String(), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_guest_invite_token", "users", ["guest_invite_token"])


def downgrade() -> None:
    op.drop_index("ix_users_guest_invite_token", table_name="users")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "guest_invite_token")
    op.drop_column("users", "is_guest")

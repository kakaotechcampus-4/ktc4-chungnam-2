"""user_identities — 사람(users)과 로그인 수단을 나눈다(#694, 2026-10-24).

카카오 사용자(provider='kakao')의 수단을 user_identities로 옮기고, 같은 리비전에서 users의 provider,
provider_user_id, is_guest와 uq_users_provider_identity를 지운다(v1 배포 전이라 레거시 칸을 남기지 않는다).
게스트(provider='guest')는 수단을 만들지 않는다 — 수단이 없는 사용자가 게스트다.

downgrade는 수단을 users로 되돌린다. 수단이 없는 사용자는 provider='guest', is_guest=true, provider_user_id는
예전처럼 재사용하지 않는 임의 값으로 채운다.

Revision ID: 0039_user_identities
Revises: 0038_place_hours
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_user_identities"
down_revision: Union[str, None] = "0038_place_hours"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_user_identities_provider_identity"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
    )
    op.execute(
        "INSERT INTO user_identities (id, user_id, provider, provider_user_id, created_at) "
        "SELECT gen_random_uuid(), id, provider, provider_user_id, created_at FROM users WHERE provider = 'kakao'"
    )
    op.drop_constraint("uq_users_provider_identity", "users", type_="unique")
    op.drop_column("users", "is_guest")
    op.drop_column("users", "provider_user_id")
    op.drop_column("users", "provider")


def downgrade() -> None:
    op.add_column("users", sa.Column("provider", sa.String(), nullable=True))
    op.add_column("users", sa.Column("provider_user_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.execute(
        "UPDATE users SET provider = i.provider, provider_user_id = i.provider_user_id "
        "FROM user_identities i WHERE i.user_id = users.id"
    )
    op.execute(
        "UPDATE users SET provider = 'guest', provider_user_id = gen_random_uuid()::text, is_guest = true "
        "WHERE provider IS NULL"
    )
    op.alter_column("users", "provider", nullable=False)
    op.alter_column("users", "provider_user_id", nullable=False)
    op.create_unique_constraint("uq_users_provider_identity", "users", ["provider", "provider_user_id"])
    op.drop_table("user_identities")

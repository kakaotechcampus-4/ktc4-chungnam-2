"""auth 모듈 첫 리비전 — users 테이블(auth/mentor-review-plan.md 후속, docs/data-model.md 10-16행).

FK 백필은 이번 리비전 범위 밖이다 — maps.created_by/memberships.user_id, pins.created_by/
reactions.user_id, recommend_runs.requested_by 등이 이미 "users(id) — auth 도착 시 FK"
주석과 함께 String으로 들어가 있는데, 그 모듈들의 기존 dev 값이 실제 users.id(UUID 문자열)와
일치한다는 보장이 없다. FK를 지금 걸면 그 값들이 위반된다 — 데이터 백필 또는 truncate 결정이
먼저 필요하다(auth/for_Root.md 보고 대상).

down_revision은 develop의 현재 최신 리비전(0004_shortlist_items)을 기준으로 잡았다 — maps
PR(#85, 0005_maps)이 아직 develop에 없다. maps가 먼저 머지되면 이 리비전 번호(0005_users)와
down_revision을 maps의 리비전 뒤로 재배치해야 한다(backend/CLAUDE.md "마이그레이션 — 체인은
하나다": 먼저 머지된 쪽이 우선, 나중 쪽이 rebase).

Revision ID: 0005_users
Revises: 0004_shortlist_items
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_users"
down_revision: Union[str, None] = "0004_shortlist_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment="탈퇴 시 soft delete, 12절"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_users_provider_identity"),
    )


def downgrade() -> None:
    op.drop_table("users")

"""maps 모듈 첫 리비전 — maps, memberships, invites 테이블
(maps/mentor-review-plan.md, maps/for_Root.md 참고).

FK는 users(id) 대상 테이블이 아직 없어 걸지 않는다(auth 도착 시 별도 리비전으로 추가 —
루트 보고 대상, 0001_pins.py와 같은 이유).

이번 리비전 범위 밖: pins.map_id·shortlist_items.map_id에 maps(id) FK를 추가하는 것.
그 두 컬럼은 지금 String이고 "map_1" 같은 dev 값이 이미 들어있을 수 있어(FK를 걸면
그 값들이 위반), 데이터 결정(truncate 또는 백필)이 먼저 필요하다 — 별도 리비전 +
루트 보고 사항(maps/for_Root.md 항목 10).

Revision ID: 0005_maps
Revises: 0004_shortlist_items
Create Date: 2026-09-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_maps"
down_revision: Union[str, None] = "0004_shortlist_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

membership_role = postgresql.ENUM("member", "owner", name="membership_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    membership_role.create(bind, checkfirst=True)

    op.create_table(
        "maps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "member_count_expected", sa.Integer(), nullable=True,
            comment="API 대응 필드 없음 — #32 확정 전까지 항상 NULL(maps/for_Root.md 항목 9)",
        ),
        sa.Column("created_by", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_maps_date_order"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), sa.ForeignKey("maps.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("map_id", "user_id", name="uq_memberships_map_user"),
    )

    op.create_table(
        "invites",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("map_id", sa.String(), sa.ForeignKey("maps.id"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("memberships")
    op.drop_table("maps")

    bind = op.get_bind()
    membership_role.drop(bind, checkfirst=True)

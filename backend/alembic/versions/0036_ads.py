"""#648 — 추천 탭 광고 테이블 2개(ads·ad_daily_stats).

ads.place_id는 places.id지만 모듈 경계라 FK를 걸지 않는다(등록 스크립트가 존재와 status=open을 검증). 같은 장소에 active
광고는 부분 유니크 인덱스 uq_ads_place_active로 하나만 둔다. ad_daily_stats는 광고별 날짜별 수만 남기고 user_id·map_id 칸이
없다. FK는 ads 안에서만 건다(ad_daily_stats.ad_id → ads.id).

docs/data-model.md ads 절, docs/ads.md 6절 참고.

Revision ID: 0036_ads
Revises: 0035_users_guest
Create Date: 2026-10-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_ads"
down_revision: Union[str, None] = "0035_users_guest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("place_id", sa.String(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("memo", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("starts_at < ends_at", name="ck_ads_period"),
    )
    op.create_index("uq_ads_place_active", "ads", ["place_id"], unique=True, postgresql_where=sa.text("active"))

    op.create_table(
        "ad_daily_stats",
        sa.Column("ad_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ads.id"), primary_key=True),
        sa.Column("stat_date", sa.Date(), primary_key=True),
        sa.Column("served_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("click_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ad_daily_stats")
    op.drop_index("uq_ads_place_active", table_name="ads")
    op.drop_table("ads")

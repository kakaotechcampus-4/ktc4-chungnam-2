"""Add maps.color and map_covers, the map's color and uploaded cover image (#1445). Expand only — old code runs on the new schema."""

from alembic import op
import sqlalchemy as sa

revision = "0066_map_cover_color"
down_revision = "0065_recommend_run_radius_m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable expand: 기존 지도는 NULL(색을 고르지 않음), 이전 코드는 이 열을 읽지 않는다.
    op.add_column("maps", sa.Column("color", sa.String(), nullable=True))
    # 지도당 한 행. 이미지 바이트는 Postgres에 둔다(S3 없음, #1203). 이전 코드는 이 테이블을 모른다.
    op.create_table(
        "map_covers",
        sa.Column("map_id", sa.String(), sa.ForeignKey("maps.id"), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("map_covers")
    op.drop_column("maps", "color")

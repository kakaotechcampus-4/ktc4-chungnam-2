"""Add memberships.last_seen_at, the member's last-seen time per map (#1556). Expand only — old code runs on the new schema."""

from alembic import op
import sqlalchemy as sa

revision = "0069_membership_last_seen_at"
down_revision = "0068_map_cover_color"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable expand: 한 번도 본 적 없으면 NULL(처음 연 지도). 이전 코드는 이 열을 읽지 않는다.
    op.add_column("memberships", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("memberships", "last_seen_at")

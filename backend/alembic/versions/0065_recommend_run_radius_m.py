"""Add recommend_runs.default_radius_m, the meter-based default radius (#1385). Expand only — old rows stay NULL."""

from alembic import op
import sqlalchemy as sa

revision = "0065_recommend_run_radius_m"
down_revision = "0064_sido_boundaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable expand: 이전 코드도 새 스키마에서 돌고, 옛 run은 default_radius_walk_min × 80m로 읽는다(core.run_radius_m).
    op.add_column("recommend_runs", sa.Column("default_radius_m", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommend_runs", "default_radius_m")

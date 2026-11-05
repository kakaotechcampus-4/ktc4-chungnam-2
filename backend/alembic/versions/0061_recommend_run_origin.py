"""Store the optional map center for recommendation runs (#1331)."""

from alembic import op
import sqlalchemy as sa

revision = "0061_recommend_run_origin"
down_revision = "0060_llm_calls_web_searches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommend_runs", sa.Column("origin_lat", sa.Float(), nullable=True))
    op.add_column("recommend_runs", sa.Column("origin_lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommend_runs", "origin_lng")
    op.drop_column("recommend_runs", "origin_lat")

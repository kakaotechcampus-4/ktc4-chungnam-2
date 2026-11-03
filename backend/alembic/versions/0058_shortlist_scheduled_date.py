"""Store the travel day of a confirmed place."""
from alembic import op
import sqlalchemy as sa

revision = "0058_shortlist_scheduled_date"
down_revision = "0057_agent_advice_state_key"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shortlist_items", sa.Column("scheduled_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("shortlist_items", "scheduled_date")

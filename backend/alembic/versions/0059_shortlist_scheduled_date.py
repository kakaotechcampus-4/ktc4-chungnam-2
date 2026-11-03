"""Store the travel day of a confirmed place."""
from alembic import op
import sqlalchemy as sa

revision = "0059_shortlist_scheduled_date"
down_revision = "0058_pin_trash"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shortlist_items", sa.Column("scheduled_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("shortlist_items", "scheduled_date")

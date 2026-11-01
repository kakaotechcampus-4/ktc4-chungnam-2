"""#951 — 장소 후기 테이블 2개(reviews·review_reports).

후기는 핀이 아니라 자체 DB 장소(places.id)에 붙는다. 한 사람이 한 장소에 하나(UNIQUE (place_id, user_id)), 신고는 후기마다 한 사람
한 번(PK). place_id와 사용자 id 열에 FK를 걸지 않는다(모듈 경계, #760). 숨김(hidden_at)은 관리 스크립트로만 바꾼다.

docs/data-model.md reviews 절, docs/credits-reviews.md 6절 참고.

Revision ID: 0049_reviews
Revises: 0048_credits
Create Date: 2026-11-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049_reviews"
down_revision: Union[str, None] = "0048_credits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("place_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("place_id", "user_id", name="uq_reviews_place_user"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating"),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 500", name="ck_reviews_body_length"),
    )
    op.create_index(
        "ix_reviews_place_created", "reviews", ["place_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("hidden_at IS NULL"),
    )
    op.create_table(
        "review_reports",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("reporter_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_reports")
    op.drop_index("ix_reviews_place_created", table_name="reviews")
    op.drop_table("reviews")

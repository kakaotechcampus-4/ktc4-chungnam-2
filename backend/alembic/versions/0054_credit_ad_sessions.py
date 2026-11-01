"""#1038 — 광고 보고 충전 세션(credit_ad_sessions).

세션을 열 때 한 줄을 만들고 받을 때 claimed_at·credited를 채운다. 하루 횟수는 오늘(KST) 연 줄의 수로 센다 —
(user_id, issued_at) 인덱스가 그 쿼리를 받는다. 사용자 id에 FK를 걸지 않는다(모듈 경계, #760). 새 테이블이라 기존 행은 없다.

docs/data-model.md credits 절, docs/credits-reviews.md 3.7, 6절 참고.

Revision ID: 0054_credit_ad_sessions
Revises: 0053_maps_withdrawal_marker
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_credit_ad_sessions"
down_revision: Union[str, None] = "0053_maps_withdrawal_marker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_ad_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credited", sa.Integer(), nullable=True),
    )
    op.create_index("ix_credit_ad_sessions_user_issued", "credit_ad_sessions", ["user_id", "issued_at"])


def downgrade() -> None:
    op.drop_index("ix_credit_ad_sessions_user_issued", table_name="credit_ad_sessions")
    op.drop_table("credit_ad_sessions")

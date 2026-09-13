"""shortlist 모듈 첫 리비전 — shortlist_items 테이블
(shortlist/mentor-review-plan.md "결정 — shortlist/flows.py::confirm_pin").

pin_id는 pins.id에 FK를 건다(pins가 이미 존재하므로 0001_pins.py처럼 미룰 이유가 없다).
map_id는 maps(id) 대상 테이블이 아직 없어 0001_pins.py와 같은 이유로 FK 없이 컬럼만 둔다
(maps 모듈 도착 시 별도 리비전으로 추가, 루트 보고 대상). visit_order는 5-10 자동계산과
#30 수동 정렬(9/4 결정, 허용 확정, docs/data-model.md) 둘 다 쓰는 컬럼이지만 이번 리비전은
값을 쓰지 않는다(for_Root.md 참고).

Revision ID: 0004_shortlist_items
Revises: 0003_recommend_runs_candidates
Create Date: 2026-09-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_shortlist_items"
down_revision: Union[str, None] = "0003_recommend_runs_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shortlist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False, comment="maps(id) — maps 모듈 도착 시 FK 추가"),
        sa.Column("pin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pins.id"), nullable=False),
        sa.Column("added_by", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("visit_order", sa.Integer(), nullable=True),
        sa.UniqueConstraint("map_id", "pin_id", name="uq_shortlist_map_pin"),
    )


def downgrade() -> None:
    op.drop_table("shortlist_items")

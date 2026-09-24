"""shortlist 모듈 두 번째 리비전 — routes 테이블 (#103, 5-10 동선 계산)
docs/data-model.md 88-109행(루트가 #103 대응으로 이미 정의) 그대로 만든다.

map_id는 0004_shortlist_items.py와 같은 이유로 FK 없이 컬럼만 둔다(maps 모듈 도착 시 별도
리비전으로 추가, 루트 보고 대상 — 0005_maps.py가 남긴 것과 동일한 성격의 미결 FK).
ordered_pin_ids/legs는 docs/api-spec.yaml Route 스키마 모양 그대로 jsonb로 저장한다
(candidates.checks와 같은 패턴, 0003 리비전 참고). unique(map_id, region_label)은
data-model.md 96행 주석대로 동시 POST 재계산의 중복 적재를 막는 방어용이다.

Revision ID: 0007_routes
Revises: 0006_users
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_routes"
down_revision: Union[str, None] = "0006_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False, comment="maps(id) — maps 모듈 도착 시 FK 추가"),
        sa.Column("region_label", sa.String(), nullable=False),
        sa.Column("ordered_pin_ids", postgresql.JSONB(), nullable=False),
        sa.Column("total_distance_m", sa.Float(), nullable=False),
        sa.Column("legs", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("map_id", "region_label", name="uq_routes_map_region"),
    )
    op.create_index("ix_routes_map_id", "routes", ["map_id"])


def downgrade() -> None:
    op.drop_index("ix_routes_map_id", table_name="routes")
    op.drop_table("routes")

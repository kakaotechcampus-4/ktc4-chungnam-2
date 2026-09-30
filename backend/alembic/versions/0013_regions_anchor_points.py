"""regions.anchor_points 추가 — #112(선호 순위 3단계, 동네 배분 tie-break)가 "그 무리의
기준 핀들까지 거리 평균"을 계산하려면 병합 전 원본 anchor 좌표 목록이 필요한데, regions
테이블은 병합된 center_lat/center_lng만 갖고 있었다(recommend/models.py, for_Root.md 보고
대상 — data-model.md엔 없는 컬럼).

server_default='[]'로 nullable=False 컬럼을 바로 추가한 뒤, 이미 있는 행은 병합된 중심
좌표 하나를 유일한 기준 핀으로 backfill한다(원본 anchor 목록은 복원할 수 없다 — 중심이 그
무리의 대표점이라는 근사).

Revision ID: 0013_regions_anchor_points
Revises: 0012_memberships_user_id_index
Create Date: 2026-09-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_regions_anchor_points"
down_revision: Union[str, None] = "0012_memberships_user_id_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "regions",
        sa.Column("anchor_points", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.execute(
        "UPDATE regions SET anchor_points = jsonb_build_array(jsonb_build_array(center_lat, center_lng)) "
        "WHERE anchor_points = '[]'::jsonb"
    )


def downgrade() -> None:
    op.drop_column("regions", "anchor_points")

"""memberships.user_id 단일 컬럼 인덱스 추가 — #137, Antigravity 검수로 발견.

GET /maps(list_maps)의 `WHERE user_id = X` 조회가 기존 (map_id, user_id) 복합 유니크
인덱스(uq_memberships_map_user)를 못 탄다 — 선두 컬럼이 map_id라 user_id 단독 조건에는
쓰이지 않는다. 순수 추가만 한다 — uq_memberships_map_user는 그대로 둔다. map_id 단독
조회(_member_count·list_members)는 그 복합 인덱스로 이미 충분해 건드리지 않는다.

Revision ID: 0012_memberships_user_id_index
Revises: 0011_maps_region
Create Date: 2026-09-29

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_memberships_user_id_index"
down_revision: Union[str, None] = "0011_maps_region"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memberships_user_id", table_name="memberships")

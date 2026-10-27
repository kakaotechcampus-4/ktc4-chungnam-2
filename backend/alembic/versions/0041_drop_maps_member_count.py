"""maps.member_count_expected 칸 삭제 — 아무도 읽거나 쓰지 않는 칸이다(#775, 결정 #760).

API 요청과 응답에 대응 필드가 없어 늘 NULL이었다. 구성원 수 N은 memberships에서 센다(#32).

downgrade는 칸을 nullable integer로 되살린다(값은 늘 NULL이었으니 채우지 않는다).

Revision ID: 0041_drop_maps_member_count
Revises: 0040_drop_places_can_recommend
Create Date: 2026-10-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_drop_maps_member_count"
down_revision: Union[str, None] = "0040_drop_places_can_recommend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("maps", "member_count_expected")


def downgrade() -> None:
    op.add_column("maps", sa.Column("member_count_expected", sa.Integer(), nullable=True))

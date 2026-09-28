"""maps.region_label / maps.region_center 추가 — 지도 만들기 지역 검색(선택), #22 변경
(PR #132, 루트 검증 후 승인, docs/CHANGELOG-api.md 2026-09-28). 둘 다 nullable이고 둘 다
있거나 둘 다 없어야 한다(CHECK) — region 없이 만드는 기존 동작은 회귀 없이 그대로 유지된다.

Revision ID: 0011_maps_region
Revises: 0010_pins_checks
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

# revision identifiers, used by Alembic.
revision: str = "0011_maps_region"
down_revision: Union[str, None] = "0010_pins_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("maps", sa.Column("region_label", sa.String(), nullable=True))
    op.add_column(
        "maps",
        sa.Column("region_center", Geography(geometry_type="POINT", srid=4326), nullable=True),
    )
    op.create_check_constraint(
        "ck_maps_region_both_or_neither",
        "maps",
        "(region_label IS NULL) = (region_center IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_maps_region_both_or_neither", "maps", type_="check")
    op.drop_column("maps", "region_center")
    op.drop_column("maps", "region_label")

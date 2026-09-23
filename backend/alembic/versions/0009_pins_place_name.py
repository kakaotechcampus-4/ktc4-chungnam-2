"""pins.place_name 컬럼 추가 — 루트 결정(2026-09-23): 장소 라벨링(가격·재료 등, places 모듈·
#53 대기)과 달리 이름은 사용자가 이미 들고 있는 값(구글맵 링크·검색 결과)이라 places 파이프
라인을 기다릴 필요가 없다. pins/schemas.py::PinCreateRequest·docs/api-spec.yaml에 같이 반영.

Revision ID: 0009_pins_place_name
Revises: 0008_evidence_regions_excl
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_pins_place_name"
down_revision: Union[str, None] = "0008_evidence_regions_excl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pins", sa.Column("place_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("pins", "place_name")

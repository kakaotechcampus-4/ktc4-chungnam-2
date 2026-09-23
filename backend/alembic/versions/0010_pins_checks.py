"""pins.checks 컬럼 추가 — #57 결정(docs/data-model.md 53-55행): 게시(「지도에 올리기」)
시점에 candidate.checks를 pins로 복사해 가드레일 5(대안 핀의 조건별 충족 체크는 게시 후에도
유지된다)를 지킨다. recommend 테이블은 참조하지 않는다(FK 없음, 값만 1회성 복사) — #124.

Revision ID: 0010_pins_checks
Revises: 0009_pins_place_name
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_pins_checks"
down_revision: Union[str, None] = "0009_pins_place_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pins", sa.Column("checks", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("pins", "checks")

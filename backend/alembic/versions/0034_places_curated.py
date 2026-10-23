"""places.curated — 정예(사람이 직접 조사·납품한 데이터) 표시(2026-10-16).

not null default false. `--authoritative` 적재가 켜고, 커버리지 적재·재계산은 끄지 않는다.
처음 한 번만 휴리스틱으로 되메운다: "출처(label_source)가 NULL인 라벨 행을 가진 장소 = 정예"(정예 납품본은 근거 없는
unknown 행을 항상 담고 인허가 커버리지 라벨은 담지 않는다 — pingo_demo에서 정예 파일 소속 15,181곳과 일치 확인).
이 마이그레이션 이후로는 휴리스틱을 쓰지 않는다. docs/data-model.md places 절 참고.

Revision ID: 0034_places_curated
Revises: 0033_places_can_recommend
Create Date: 2026-10-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_places_curated"
down_revision: Union[str, None] = "0033_places_can_recommend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("places", sa.Column("curated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.execute(
        "UPDATE places SET curated = true "
        "WHERE EXISTS (SELECT 1 FROM place_facts f WHERE f.place_id = places.id AND f.label_source IS NULL)"
    )


def downgrade() -> None:
    op.drop_column("places", "curated")

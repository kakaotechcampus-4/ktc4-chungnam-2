"""places.can_recommend — AI 추천 후보 풀에 들어가도 되는 장소인가(2026-10-15 결정).

not null default false. 값은 places의 재계산(`python -m places.scripts.recompute_can_recommend`)이 라벨로 채운다 —
이 마이그레이션은 값을 채우지 않는다(기존 행은 false). 적용한 뒤 재계산을 한 번 돌려야 추천 후보가 생긴다.
인덱스는 더하지 않는다: 후보 검색은 기존 GiST(idx_places_geom)로 반경을 먼저 거르고 category·status·can_recommend는
그 결과에 얹는 조건이라, 대부분이 true인 불리언에 별도 인덱스를 두는 이득이 없다.
docs/data-model.md places 절, docs/constraints.md「추천 가능」참고.

Revision ID: 0033_places_can_recommend
Revises: 0032_feedback
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_places_can_recommend"
down_revision: Union[str, None] = "0032_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("places", sa.Column("can_recommend", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("places", "can_recommend")

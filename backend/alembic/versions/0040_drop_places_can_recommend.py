"""places.can_recommend 칸 삭제 — 추천 후보는 places.curated를 바로 읽는다(#743, 멘토 리뷰 #680).

can_recommend 규칙이 "curated와 같다"(#681)가 된 뒤에도 따로 저장된 칸이라, 규칙을 바꾸면 재계산이나 적재를 돌려야 값이
바뀌었다. 칸을 없애고 `search_nearby_own`이 curated를 읽는다.

downgrade는 칸을 되살리고(not null default false) curated 값으로 채운다.

Revision ID: 0040_drop_places_can_recommend
Revises: 0039_user_identities
Create Date: 2026-10-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_drop_places_can_recommend"
down_revision: Union[str, None] = "0039_user_identities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("places", "can_recommend")


def downgrade() -> None:
    op.add_column("places", sa.Column("can_recommend", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.execute("UPDATE places SET can_recommend = curated")

"""#157 — category enum에 「기타」 추가, AI 핀의 reason·member_fulfillment·place_source 컬럼.

reason/member_fulfillment/place_source는 0010 checks와 같은 패턴이다: 게시(「지도에 올리기」)
시점에 candidate 값을 복사하고 recommend 테이블은 참조하지 않는다(FK 없음). 값은 recommend가
채우므로 직접 찍은 핀·아직 값이 없는 핀은 NULL. recommend_category는 건드리지 않는다.

Revision ID: 0016_pins_spec_gaps
Revises: 0014_users_sessions_valid_after
Create Date: 2026-09-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016_pins_spec_gaps"
# 0015(recommend)가 develop에 들어오면 그 revision으로 바꾼다 — 머지 전 헤드가 하나인지 확인할 것.
down_revision: Union[str, None] = "0014_users_sessions_valid_after"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE는 트랜잭션 밖에서 실행해야 한다.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE category ADD VALUE IF NOT EXISTS '기타'")
    op.add_column("pins", sa.Column("reason", sa.String, nullable=True))
    op.add_column("pins", sa.Column("member_fulfillment", JSONB, nullable=True))
    op.add_column("pins", sa.Column("place_source", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("pins", "place_source")
    op.drop_column("pins", "member_fulfillment")
    op.drop_column("pins", "reason")
    # PostgreSQL은 enum 값을 지울 수 없다 — 「기타」는 남긴다(무해).

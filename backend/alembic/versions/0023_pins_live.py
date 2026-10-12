"""#382 — 실시간 핀(source='live'): 자체 DB에 없는 장소를 카카오 장소 ID·검색어·메모만으로 남긴다.

- pins.place_id·geom을 NULL 허용으로, source('db'|'live')·kakao_place_id·search_query·memo를 추가한다.
  기존 행은 모두 source='db'다.
- CHECK(ck_pins_source_fields): db는 place_id·geom 필수, live는 둘 다 NULL이고 kakao_place_id·search_query 필수.
- 부분 유니크 uq_pins_map_kakao_place: 같은 지도에서 같은 카카오 장소 ID의 live 핀은 하나(삭제된 핀 제외).

downgrade는 place_id·geom을 다시 NOT NULL로 되돌려야 해서 live 핀을 반응·확정 항목과 함께 지운다.
docs/data-model.md pins, docs/CHANGELOG-api.md 2026-10-07(두 번째) 참고.

Revision ID: 0023_pins_live
Revises: 0022_reaction_two_state
Create Date: 2026-10-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_pins_live"
down_revision: Union[str, None] = "0022_reaction_two_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

pin_source = postgresql.ENUM("db", "live", name="pin_source", create_type=False)

_LIVE = "SELECT id FROM pins WHERE source = 'live'"


def upgrade() -> None:
    pin_source.create(op.get_bind(), checkfirst=True)
    op.add_column("pins", sa.Column("source", pin_source, nullable=False, server_default="db"))
    op.add_column("pins", sa.Column("kakao_place_id", sa.String(), nullable=True))
    op.add_column("pins", sa.Column("search_query", sa.String(), nullable=True))
    op.add_column("pins", sa.Column("memo", sa.String(), nullable=True))
    op.alter_column("pins", "place_id", existing_type=sa.String(), nullable=True)
    op.execute("ALTER TABLE pins ALTER COLUMN geom DROP NOT NULL")   # geography 컬럼이라 raw SQL이 가장 단순하다
    op.create_check_constraint(
        "ck_pins_source_fields", "pins",
        "(source = 'db' AND place_id IS NOT NULL AND geom IS NOT NULL) OR "
        "(source = 'live' AND place_id IS NULL AND geom IS NULL "
        "AND kakao_place_id IS NOT NULL AND search_query IS NOT NULL)",
    )
    op.create_index(
        "uq_pins_map_kakao_place", "pins", ["map_id", "kakao_place_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND kakao_place_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pins_map_kakao_place", table_name="pins")
    op.drop_constraint("ck_pins_source_fields", "pins", type_="check")
    op.execute(f"DELETE FROM reactions WHERE pin_id IN ({_LIVE})")
    op.execute(f"DELETE FROM shortlist_items WHERE pin_id IN ({_LIVE})")
    op.execute("DELETE FROM pins WHERE source = 'live'")
    op.execute("ALTER TABLE pins ALTER COLUMN geom SET NOT NULL")
    op.alter_column("pins", "place_id", existing_type=sa.String(), nullable=False)
    op.drop_column("pins", "memo")
    op.drop_column("pins", "search_query")
    op.drop_column("pins", "kakao_place_id")
    op.drop_column("pins", "source")
    pin_source.drop(op.get_bind(), checkfirst=True)

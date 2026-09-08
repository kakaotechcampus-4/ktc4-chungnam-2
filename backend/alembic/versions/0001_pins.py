"""pins 모듈 첫 리비전 — pins, reactions 테이블

FK는 users(id)/maps(id)/places(id) 대상 테이블이 아직 없어 걸지 않는다
(auth/maps/places 도착 시 별도 리비전으로 추가 — 루트 보고 대상).

Revision ID: 0001_pins
Revises:
Create Date: 2026-09-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_pins"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

category = postgresql.ENUM("음식점", "카페", "숙소", "관광지", name="category", create_type=False)
pin_kind = postgresql.ENUM("일반", "AI추천", "확정", name="pin_kind", create_type=False)
pin_origin = postgresql.ENUM("direct", "ai", name="pin_origin", create_type=False)
visibility = postgresql.ENUM("public", "private", name="visibility", create_type=False)
reaction_type = postgresql.ENUM("like", "neutral", "against", name="reaction_type", create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    bind = op.get_bind()
    category.create(bind, checkfirst=True)
    pin_kind.create(bind, checkfirst=True)
    pin_origin.create(bind, checkfirst=True)
    visibility.create(bind, checkfirst=True)
    reaction_type.create(bind, checkfirst=True)

    op.create_table(
        "pins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False, comment="maps(id) — maps 모듈 도착 시 FK 추가"),
        sa.Column("category", category, nullable=False),
        sa.Column("kind", pin_kind, nullable=False),
        sa.Column("origin", pin_origin, nullable=False),
        sa.Column("place_id", sa.String(), nullable=False, comment="places(id) — places 모듈 도착 시 FK 추가"),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("visibility", visibility, nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_pins_map_place",
        "pins",
        ["map_id", "place_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pins.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("type", reaction_type, nullable=False),
        sa.Column("reason_text", sa.String(), nullable=True),
        sa.Column("reason_chip_ids", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pin_id", "user_id", name="uq_reactions_pin_user"),
    )


def downgrade() -> None:
    op.drop_table("reactions")
    op.drop_index("uq_pins_map_place", table_name="pins")
    op.drop_table("pins")

    bind = op.get_bind()
    reaction_type.drop(bind, checkfirst=True)
    visibility.drop(bind, checkfirst=True)
    pin_origin.drop(bind, checkfirst=True)
    pin_kind.drop(bind, checkfirst=True)
    category.drop(bind, checkfirst=True)

    # postgis extension은 다른 모듈도 쓸 수 있으니 내리지 않는다.

"""#189 — 자체 장소 DB: places, place_facts (docs/data-model.md "places / place_facts").

카카오 응답은 저장하지 않는다(#53). places의 이름·좌표·주소는 인허가 공공데이터·TourAPI에서만 오고,
kakao_place_id/url/matched_at만 사용자가 장소를 고를 때 한 건씩 기록한다. 숙소·기타 분류는 없다.
pins.place_id가 places.id를 가리키도록 바꾸는 것은 pins의 몫(#195)이라 여기서 pins를 건드리지 않는다.

번호: 0016은 0016_pins_spec_gaps가 이미 쓰고 있다. 헤드가 0015_recommend_gaps_158_146이라 거기서 잇는다 —
PR 올리기 직전 `alembic heads`가 하나인지 확인할 것.

Revision ID: 0017_places_own_db
Revises: 0015_recommend_gaps_158_146
Create Date: 2026-10-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision: str = "0017_places_own_db"
down_revision: Union[str, None] = "0015_recommend_gaps_158_146"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    place_category = postgresql.ENUM("음식점", "카페", "관광지", name="place_category", create_type=False)
    place_source = postgresql.ENUM("permit", "tourapi", name="place_source", create_type=False)
    place_status = postgresql.ENUM("open", "closed", name="place_status", create_type=False)
    fact_confidence = postgresql.ENUM("known", "unknown", name="fact_confidence", create_type=False)
    for enum in (place_category, place_source, place_status, fact_confidence):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "places",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", place_source, nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", place_category, nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("status", place_status, nullable=False, server_default="open"),
        sa.Column("kakao_place_id", sa.String(), nullable=True),
        sa.Column("kakao_place_url", sa.String(), nullable=True),
        sa.Column("kakao_matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_id", name="uq_places_source_source_id"),
    )
    # 반경 검색(ST_DWithin)·매칭 후보 조회용 GiST. 모델의 기본 spatial_index 이름과 같다.
    op.create_index("idx_places_geom", "places", ["geom"], postgresql_using="gist")

    op.create_table(
        "place_facts",
        sa.Column("place_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("places.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fact_key", sa.String(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", fact_confidence, nullable=False),
        sa.Column("source_layer", sa.SmallInteger(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_layer IN (1, 2, 3)", name="ck_place_facts_source_layer"),
    )


def downgrade() -> None:
    op.drop_table("place_facts")
    op.drop_index("idx_places_geom", table_name="places")
    op.drop_table("places")
    bind = op.get_bind()
    for name in ("fact_confidence", "place_status", "place_source", "place_category"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)

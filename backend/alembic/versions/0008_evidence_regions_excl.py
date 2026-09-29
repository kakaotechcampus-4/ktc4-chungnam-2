"""recommend 모듈 두 번째 리비전 — evidence_lines, regions, exclusions 테이블 + candidates에
지연됐던 region_id FK 추가(regions가 이제 생겼다) + recommend_runs.last_funnel 추가
(recommend/#108 코어 파이프라인, recommend/for_Root.md 참고).

FK는 users(id)/maps(id) 대상 테이블이 이제 존재하지만(0005_maps/0006_users) 걸지 않는다 —
그 두 리비전이 남긴 이유와 동일하다: 기존 dev 값(예: "map_1", "user_1")이 실제 maps.id/users.id
와 일치한다는 보장이 없어 FK를 걸면 즉시 위반된다(백필/truncate 결정이 먼저 필요, 루트 보고 대상).
candidates.region_id는 이번엔 대상 테이블(regions)이 이 리비전 안에서 같이 생기므로 FK를 건다 —
0001/0005/0006이 미룬 것과 성격이 다르다(대상이 이미 있고, 기존 candidates 행의 region_id는
전부 NULL이라 위반 여지가 없다).

regions.geom(docs/data-model.md의 geography 컬럼)은 만들지 않는다 — recommend/models.py
모듈 docstring에 이유를 적었다(places 없이 label을 만들 방법이 없어 병합된 원(중심+반경)을
평범한 float로 저장, PostGIS 대신). for_Root.md에 별도 보고.

Revision ID: 0008_evidence_regions_excl
Revises: 0007_routes
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic. 짧게 줄인 이유: alembic_version.version_num이
# varchar(32)라 "0008_recommend_evidence_regions_exclusions"(43자)는 그 자리에서 바로
# StringDataRightTruncation으로 실패한다(직접 확인) — 32자 이내로 줄였다.
revision: str = "0008_evidence_regions_excl"
down_revision: Union[str, None] = "0007_routes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

recommend_evidence_source = postgresql.ENUM("reaction", "manual", name="recommend_evidence_source", create_type=False)
recommend_evidence_badge = postgresql.ENUM(
    "required", "preferred", "reference", name="recommend_evidence_badge", create_type=False
)
recommend_exclusion_reason = postgresql.ENUM("proposed", "dismissed", name="recommend_exclusion_reason", create_type=False)
recommend_category = postgresql.ENUM(
    "음식점", "카페", "숙소", "관광지", name="recommend_category", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    recommend_evidence_source.create(bind, checkfirst=True)
    recommend_evidence_badge.create(bind, checkfirst=True)
    recommend_exclusion_reason.create(bind, checkfirst=True)

    op.add_column("recommend_runs", sa.Column("last_funnel", postgresql.JSONB(), nullable=True))

    op.create_table(
        "evidence_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recommend_runs.id"), nullable=False),
        sa.Column("author_id", sa.String(), nullable=False, comment="users(id) — 백필 전까지 FK 없음"),
        sa.Column("source", recommend_evidence_source, nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("chip_id", sa.String(), nullable=True),
        sa.Column("badge", recommend_evidence_badge, nullable=False),
        sa.Column("fact_key", sa.String(), nullable=True),
        sa.Column("circle_anchor_pin_id", sa.String(), nullable=True, comment="pins(id) — 크로스 모듈 FK 없음"),
        sa.Column("circle_radius_m", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recommend_runs.id"), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("center_lat", sa.Float(), nullable=False),
        sa.Column("center_lng", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_foreign_key("fk_candidates_region_id_regions", "candidates", "regions", ["region_id"], ["id"])

    op.create_table(
        "exclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False, comment="maps(id) — 백필 전까지 FK 없음"),
        sa.Column("category", recommend_category, nullable=False),
        sa.Column("place_id", sa.String(), nullable=False, comment="places(id) — places 모듈 도착 시 FK 추가"),
        sa.Column("reason", recommend_exclusion_reason, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recommend_runs.id"), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False, comment="users(id) — 백필 전까지 FK 없음"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("map_id", "requested_by", "place_id", name="uq_exclusions_map_requester_place"),
    )


def downgrade() -> None:
    op.drop_table("exclusions")
    op.drop_constraint("fk_candidates_region_id_regions", "candidates", type_="foreignkey")
    op.drop_table("regions")
    op.drop_table("evidence_lines")
    op.drop_column("recommend_runs", "last_funnel")

    bind = op.get_bind()
    recommend_exclusion_reason.drop(bind, checkfirst=True)
    recommend_evidence_badge.drop(bind, checkfirst=True)
    recommend_evidence_source.drop(bind, checkfirst=True)

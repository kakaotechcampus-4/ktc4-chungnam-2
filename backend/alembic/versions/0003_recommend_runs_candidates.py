"""recommend 모듈 첫 리비전 — recommend_runs, candidates 테이블
(recommend/mentor-review-plan.md "착수 가능해지는 조건" 2번 — flows.py::publish_candidate에
필요한 최소 스켈레톤). evidence_lines/regions/exclusions은 후속 세션이 별도 리비전으로 추가한다.

FK는 users(id)/maps(id)/places(id) 대상 테이블이 아직 없어 걸지 않는다(0001_pins.py와 같은
이유 — auth/maps/places 도착 시 별도 리비전으로 추가, 루트 보고 대상). candidates.region_id도
같은 이유로 FK 없이 컬럼만 둔다(regions 테이블이 아직 없음).

candidates.lat/lng는 docs/data-model.md의 candidates 정의(117-159행)엔 없는 컬럼이다 —
recommend/models.py 모듈 docstring에 이유를 적었다(places 온디맨드 조회가 아직 없어 pins.geom과
같은 이유로 denormalize). for_Root.md에 별도 보고.

Revision ID: 0003_recommend_runs_candidates
Revises: 0002_event_log
Create Date: 2026-09-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_recommend_runs_candidates"
down_revision: Union[str, None] = "0002_event_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

recommend_category = postgresql.ENUM(
    "음식점", "카페", "숙소", "관광지", name="recommend_category", create_type=False
)
recommend_run_status = postgresql.ENUM(
    "collecting_evidence", "awaiting_region_confirm", "executing", "done", "failed",
    name="recommend_run_status", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    recommend_category.create(bind, checkfirst=True)
    recommend_run_status.create(bind, checkfirst=True)

    op.create_table(
        "recommend_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("map_id", sa.String(), nullable=False, comment="maps(id) — maps 모듈 도착 시 FK 추가"),
        sa.Column("category", recommend_category, nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False, comment="users(id) — auth 모듈 도착 시 FK 추가"),
        sa.Column("status", recommend_run_status, nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recommend_runs.id"), nullable=False),
        sa.Column("place_id", sa.String(), nullable=False, comment="places(id) — places 모듈 도착 시 FK 추가"),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=True, comment="regions(id) — 지역확인 세션 도착 시 FK 추가"),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("member_fulfillment", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("published_pin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("candidates")
    op.drop_table("recommend_runs")

    bind = op.get_bind()
    recommend_run_status.drop(bind, checkfirst=True)
    recommend_category.drop(bind, checkfirst=True)

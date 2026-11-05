"""sido_boundaries — 시·도 경계 표(#1385). 지역 판정의 정본이다(places.api.sido_at, circle_outside_region).

표를 더하기만 한다(expand). 이전 서버는 이 표를 읽지 않고, 표가 비어 있으면 새 서버도 가장 가까운 장소 주소로 판정하던 방식으로 돌아간다.
행은 `python -m places.load boundaries`가 넣는다(통계청 2018 시·도 경계, 코드 11…39). 사용자 id 열이 없어 게스트 합치기·탈퇴 목록은 그대로다.
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0064_sido_boundaries"
down_revision = "0063_agent_suggestion_followup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "sido_boundaries",
        sa.Column("code", sa.String(), primary_key=True),   # 통계청 시·도 코드 "11"…"39"
        sa.Column("name", sa.String(), nullable=False),     # places.core.sido와 같은 짧은 이름. 전남·광주는 둘 다 "전남광주"
        sa.Column("geom", Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False),
        sa.Column("source_sha256", sa.String(), nullable=False),   # 적재한 경계 파일의 해시 — FE 정본과 맞는지 가린다
    )
    op.create_index("ix_sido_boundaries_name", "sido_boundaries", ["name"])


def downgrade() -> None:
    op.drop_index("ix_sido_boundaries_name", table_name="sido_boundaries")
    op.drop_table("sido_boundaries")

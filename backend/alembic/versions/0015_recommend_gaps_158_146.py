"""recommend: 숙소 제거(#146) + Candidate 가드레일5 필드·반경 넓히기 상태(#158).

1) recommend_category enum에서 숙소를 뺀다. **기존 숙소 run 처리**: 숙소 run과 그 하위 행
   (evidence_lines/regions/candidates)과 숙소 exclusions를 지운다. 이 테이블들은 요청자 개인의
   작업 상태(근거 조립·대안 후보·재시도 제외목록)라 숙소가 추천 대상에서 빠지면 더 쓸 곳이
   없다. **이미 지도에 올린(게시된) 핀은 pins 소유라 그대로 남는다** — candidates는 지워져도
   pins에 checks가 복사돼 있어 가드레일 5(게시 뒤 유지)가 깨지지 않는다. 지운 행은 downgrade로
   복원되지 않는다(enum 값만 되돌린다).
2) candidates.reason(text)·place_source(jsonb) 추가 — 둘 다 nullable(기존 행은 근거를 지어내지
   않고 비워 둔다). member_fulfillment는 컬럼이 이미 있고 모양만 스펙({satisfied,total,by_member})으로
   바뀐다 — 기존 행의 옛 모양({member_id:[fact_key]})은 비운다('{}' = 집계 없음).
3) recommend_runs.default_radius_walk_min(int, 기본 15) — 반경 넓히기 누적 상태. 응답
   RecommendRun.default_radius_walk_min의 정본이다.

Revision ID: 0015_recommend_gaps_158_146
Revises: 0016_pins_spec_gaps
Create Date: 2026-09-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_recommend_gaps_158_146"
down_revision: Union[str, None] = "0016_pins_spec_gaps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WITH_LODGING = ("음식점", "카페", "숙소", "관광지")
_WITHOUT_LODGING = ("음식점", "카페", "관광지")


def _replace_category_enum(values: Sequence[str]) -> None:
    op.execute("ALTER TYPE recommend_category RENAME TO recommend_category_old")
    new_type = postgresql.ENUM(*values, name="recommend_category")
    new_type.create(op.get_bind())
    for table in ("recommend_runs", "exclusions"):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN category TYPE recommend_category "
            "USING category::text::recommend_category"
        )
    op.execute("DROP TYPE recommend_category_old")


def upgrade() -> None:
    # 숙소 run과 하위 행 정리 — FK 순서(자식 먼저).
    lodging_runs = "(SELECT id FROM recommend_runs WHERE category = '숙소')"
    for child in ("candidates", "regions", "evidence_lines"):
        op.execute(f"DELETE FROM {child} WHERE run_id IN {lodging_runs}")
    op.execute("DELETE FROM exclusions WHERE category = '숙소' OR run_id IN " + lodging_runs)
    op.execute("DELETE FROM recommend_runs WHERE category = '숙소'")
    _replace_category_enum(_WITHOUT_LODGING)

    op.add_column("candidates", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("candidates", sa.Column("place_source", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE candidates SET member_fulfillment = '{}'::jsonb")
    op.add_column(
        "recommend_runs",
        sa.Column("default_radius_walk_min", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    op.drop_column("recommend_runs", "default_radius_walk_min")
    op.drop_column("candidates", "place_source")
    op.drop_column("candidates", "reason")
    _replace_category_enum(_WITH_LODGING)

"""agent_map_status 테이블, agent_suggestions.facts — 지도 현황 문단(8.2)과 우리 데이터 확인(6.6) (#1168, 결정 #1152).

- agent_map_status: 지도마다 최신 현황 문단 하나. 코드가 센 칸(cells)과 그 해시, 모델이 고른 카테고리별 상태, 검증을 통과한 문단.
  사유 원문, 구성원 이름, 장소 이름은 없다(docs/agent-v2.md 2절 11, 13번). map_id에 FK는 걸지 않는다(모듈 경계, #760).
- agent_suggestions.facts: 우리 데이터 확인 줄의 (pin_id, fact_key)만. 값은 응답·이벤트를 만들 때 places에서 다시 읽는다.
새 테이블과 기본값 있는 열이라 기존 행에 영향이 없다(expand). agent_runs의 trigger(status)와 outcome(status_updated)은 text라
마이그레이션이 없다.

Revision ID: 0056_agent_map_status_facts
Revises: 0055_place_external_ids
Create Date: 2026-11-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_agent_map_status_facts"
down_revision: Union[str, None] = "0055_place_external_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_map_status",
        sa.Column("map_id", sa.String(), primary_key=True),
        sa.Column("cells", postgresql.JSONB(), nullable=False),
        sa.Column("cells_hash", sa.String(), nullable=False),
        sa.Column("states", postgresql.JSONB(), nullable=False),
        sa.Column("paragraph", sa.String(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "agent_suggestions",
        sa.Column("facts", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_suggestions", "facts")
    op.drop_table("agent_map_status")

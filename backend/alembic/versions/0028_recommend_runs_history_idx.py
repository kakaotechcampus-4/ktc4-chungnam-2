"""#469 — 지난 추천 기록 조회용 인덱스.

GET /maps/{mapId}/runs는 (map_id, requested_by)로 거르고 created_at 내림차순으로 읽는다.

Revision ID: 0028_recommend_runs_history_idx
Revises: 0024_evidence_lines_seq
Create Date: 2026-10-13

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0028_recommend_runs_history_idx"
down_revision: Union[str, None] = "0024_evidence_lines_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_recommend_runs_map_requester_created"


def upgrade() -> None:
    op.execute(f"CREATE INDEX {INDEX} ON recommend_runs (map_id, requested_by, created_at DESC)")


def downgrade() -> None:
    op.drop_index(INDEX, table_name="recommend_runs")

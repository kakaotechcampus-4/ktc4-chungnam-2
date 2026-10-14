"""#467 — 초대 링크를 끌 수 있게 하고(revoked_at), 목록을 위해 만든 시각·지도별 인덱스를 둔다.

revoked_at은 방장이 링크를 끈 시각이다(NULL이면 켜져 있음). created_at은 목록 정렬(최신순)과 "내가 만든
유효한 링크 재사용"의 기준이다. 기존 행에는 컬럼을 추가하는 시각이 들어간다(실제 발급 시각은 알 수 없다).
map_id 인덱스는 지도별 목록·재사용 조회용이다.

docs/data-model.md invites 참고.

Revision ID: 0025_invite_revoke
Revises: 0028_recommend_runs_history_idx
Create Date: 2026-10-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_invite_revoke"
down_revision: Union[str, None] = "0028_recommend_runs_history_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invites", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "invites",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invites_map_id", "invites", ["map_id"])


def downgrade() -> None:
    op.drop_index("ix_invites_map_id", table_name="invites")
    op.drop_column("invites", "created_at")
    op.drop_column("invites", "revoked_at")

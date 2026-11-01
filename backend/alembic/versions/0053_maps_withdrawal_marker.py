"""maps.deleted_by_withdrawal_of — 탈퇴가 지운 지도의 표식 (#1000).

탈퇴(maps.transfer_or_delete_owned_maps)가 후임 없는 방장의 지도를 삭제할 때 탈퇴자의 user id를 남긴다. 계정을 7일 안에
되살리면(#855) 이 표식이 그 사람인 지도를 되살린다. 직접 지운 지도와 위임된 지도는 NULL이다. 정리 작업(maps.purge)은 지도
행째 지우므로 표식도 함께 사라진다. 기존 행은 모두 NULL(expand, 비어도 된다).

Revision ID: 0053_maps_withdrawal_marker
Revises: 0052_llm_calls_batch_discard
Create Date: 2026-11-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_maps_withdrawal_marker"
down_revision: Union[str, None] = "0052_llm_calls_batch_discard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("maps", sa.Column("deleted_by_withdrawal_of", sa.String(), nullable=True))
    # 계정 복구가 이 사람의 표식 지도만 찾는다. 대부분의 행은 NULL이라 부분 인덱스로 둔다.
    op.create_index(
        "ix_maps_deleted_by_withdrawal_of", "maps", ["deleted_by_withdrawal_of"],
        postgresql_where=sa.text("deleted_by_withdrawal_of IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_maps_deleted_by_withdrawal_of", table_name="maps")
    op.drop_column("maps", "deleted_by_withdrawal_of")

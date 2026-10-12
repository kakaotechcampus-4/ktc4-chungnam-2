"""#369 — 지도 삭제(soft delete)와 방장 1명 제약.

- maps.deleted_at: 방장이 삭제하면 찍는다. 찍힌 지도는 모든 조회 경로에서 없는 지도(404)로 보인다.
- memberships의 (map_id) WHERE role = 'owner' 부분 유니크 인덱스: 지도당 방장은 최대 1명.

인덱스를 만들기 전에 방장이 2명 이상인 지도가 있는지 먼저 본다. 있으면 어느 쪽을 남길지는 사람이
정할 일이라 여기서 고치지 않고 지도 id를 담아 실패한다(유니크 위반 에러보다 원인이 바로 보이게).
docs/data-model.md maps·memberships 참고.

Revision ID: 0021_maps_delete_leave
Revises: 0020_evidence_wants
Create Date: 2026-10-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_maps_delete_leave"
down_revision: Union[str, None] = "0020_evidence_wants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("maps", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    duplicated = op.get_bind().execute(sa.text(
        "SELECT map_id FROM memberships WHERE role = 'owner' GROUP BY map_id HAVING count(*) > 1"
    )).scalars().all()
    if duplicated:
        raise RuntimeError(
            f"방장이 2명 이상인 지도가 있어 uq_memberships_one_owner_per_map을 만들 수 없다: {duplicated} — "
            "남길 방장을 정해 나머지를 'member'로 바꾼 뒤 다시 실행한다"
        )
    op.create_index(
        "uq_memberships_one_owner_per_map", "memberships", ["map_id"],
        unique=True, postgresql_where=sa.text("role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_index("uq_memberships_one_owner_per_map", table_name="memberships")
    op.drop_column("maps", "deleted_at")

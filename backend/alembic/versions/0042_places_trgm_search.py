"""places.name·address에 pg_trgm GIN 인덱스 — 장소 검색의 ILIKE '%검색어%'가 전체를 훑지 않게(#822).

검색어가 3자 이상일 때 인덱스를 탄다. 2자 이하(예: 「안국」)는 pg_trgm이 쓸 조각이 없어 전체를 훑는다.

Revision ID: 0042_places_trgm_search
Revises: 0041_drop_maps_member_count
Create Date: 2026-10-30

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0042_places_trgm_search"
down_revision: Union[str, None] = "0041_drop_maps_member_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in ("name", "address"):
        op.execute(f"CREATE INDEX idx_places_{column}_trgm ON places USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    for column in ("name", "address"):
        op.execute(f"DROP INDEX idx_places_{column}_trgm")

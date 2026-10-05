"""#195 — 핀이 자체 DB 장소(places.id)를 가리킨다: pins.place_name 제거, 개발 중 쌓인 핀 정리.

v1의 핀은 모두 자체 DB 장소다. 이름은 places.name에서 읽으므로 핀에 저장하지 않는다. 지금까지의 핀은
카카오 검색 응답의 이름·좌표·장소 ID를 그대로 저장한 개발 데이터라(#53에서 저장 금지) places.id를 가리키지
않는다 — 배포 전에 지워야 하는 데이터라 places 행에 대응되지 않는 핀은 의존 행과 함께 삭제한다.
places.id와 일치하는 핀은 남긴다(없다면 전부 삭제된다). place_id 컬럼은 문자열을 유지한다(FK·UUID 타입 미적용).

Revision ID: 0018_pins_own_db_places
Revises: 0017_places_own_db
Create Date: 2026-10-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_pins_own_db_places"
down_revision: Union[str, None] = "0017_places_own_db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORPHAN = "SELECT id FROM pins WHERE place_id NOT IN (SELECT id::text FROM places)"


def upgrade() -> None:
    # pins.id를 참조하는 행(FK)부터 지운다: reactions, shortlist_items.
    op.execute(f"DELETE FROM reactions WHERE pin_id IN ({_ORPHAN})")
    op.execute(f"DELETE FROM shortlist_items WHERE pin_id IN ({_ORPHAN})")
    op.execute("DELETE FROM pins WHERE place_id NOT IN (SELECT id::text FROM places)")
    op.drop_column("pins", "place_name")


def downgrade() -> None:
    # 지운 핀은 되살리지 않는다. 컬럼만 되돌린다.
    op.add_column("pins", sa.Column("place_name", sa.String, nullable=True))

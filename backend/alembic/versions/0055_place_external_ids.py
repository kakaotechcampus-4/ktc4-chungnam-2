"""place_external_ids, place_external_id_votes — 카카오·네이버 장소 번호 → 자체 DB 장소 번호표 (#1048).

카톡 링크는 장소 번호뿐이라 한 번 이어진 짝을 다음 사람부터 한 번에 찍는다. 번호만 저장한다(이름·좌표·주소 없음, 카카오 약관 #53).
새 테이블 둘이라 기존 행에 영향이 없다(expand). 표(votes)는 voter_hash(사용자 id의 단방향 해시)당 한 표이고 탈퇴 정리가 지운다.

Revision ID: 0055_place_external_ids
Revises: 0054_credit_ad_sessions
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_place_external_ids"
down_revision: Union[str, None] = "0054_credit_ad_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "place_external_ids",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("place_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "external_id", "place_id", name="uq_place_external_ids_pair"),
        sa.CheckConstraint("provider IN ('kakao', 'naver')", name="ck_place_external_ids_provider"),
        sa.CheckConstraint("source IN ('hint', 'user')", name="ck_place_external_ids_source"),
    )
    op.create_index("idx_place_external_ids_lookup", "place_external_ids", ["provider", "external_id"])
    op.create_table(
        "place_external_id_votes",
        sa.Column("external_id_row", postgresql.UUID(as_uuid=True), sa.ForeignKey("place_external_ids.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("voter_hash", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_place_external_id_votes_voter", "place_external_id_votes", ["voter_hash"])


def downgrade() -> None:
    op.drop_index("idx_place_external_id_votes_voter", table_name="place_external_id_votes")
    op.drop_table("place_external_id_votes")
    op.drop_index("idx_place_external_ids_lookup", table_name="place_external_ids")
    op.drop_table("place_external_ids")

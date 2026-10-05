"""#207(#203) — place_facts.evidence / label_source: 라벨의 근거 원문과 근거의 종류.

음식점 납품본 라벨마다 근거(예: "인허가 업태 '일식'")와 출처 종류(license_business_type, 모범음식점 …)가 따라온다.
가드레일 5의 "이유·출처"를 만드는 재료라 라벨과 같이 저장한다. 근거가 없는 라벨(unknown 등)은 NULL.
docs/data-model.md place_facts 참고(PR #206).

Revision ID: 0019_place_facts_evidence
Revises: 0018_pins_own_db_places
Create Date: 2026-10-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_place_facts_evidence"
down_revision: Union[str, None] = "0018_pins_own_db_places"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("place_facts", sa.Column("evidence", sa.Text(), nullable=True))
    op.add_column("place_facts", sa.Column("label_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("place_facts", "label_source")
    op.drop_column("place_facts", "evidence")

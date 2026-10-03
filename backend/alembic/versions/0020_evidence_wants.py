"""#231 — evidence_lines.wants: 사유의 방향(#228).

이 특징(fact_key)이 있는 장소를 원하는가. true=원함, false=원하지 않음, null=모름.
기존 행은 방향이 없던 시절 데이터라 NULL로 두고, 코드는 NULL을 이전 동작 그대로 읽는다.
docs/data-model.md evidence_lines, docs/constraints.md "사유의 방향(wants)과 실격" 참고.

Revision ID: 0020_evidence_wants
Revises: 0019_place_facts_evidence
Create Date: 2026-10-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_evidence_wants"
down_revision: Union[str, None] = "0019_place_facts_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence_lines", sa.Column("wants", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_lines", "wants")

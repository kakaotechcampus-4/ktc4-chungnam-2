"""#428 — evidence_lines에 넣은 순서(seq)를 둔다.

created_at은 server_default=now()라 PostgreSQL에서 트랜잭션 시작 시각이다. run 생성 때 한 트랜잭션에서 넣는 근거 줄은
모두 같은 created_at을 갖고 id는 무작위 UUID라, ORDER BY created_at만으로는 "한 반응의 글 줄 다음에 칩 줄"(#412, #419)
같은 순서가 보장되지 않는다. seq(bigint identity)를 더해 ORDER BY created_at, seq로 읽는다.
기존 행에는 컬럼을 추가할 때 번호가 자동으로 매겨진다. API 응답에는 넣지 않는다.

docs/data-model.md evidence_lines 참고.

Revision ID: 0024_evidence_lines_seq
Revises: 0023_pins_live
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0024_evidence_lines_seq"
down_revision: Union[str, None] = "0023_pins_live"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE evidence_lines ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY")


def downgrade() -> None:
    op.drop_column("evidence_lines", "seq")

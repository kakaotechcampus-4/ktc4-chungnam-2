"""places.name_norm(이름 정규형) 생성 열과 접두 검색용 btree 인덱스 — 장소 검색의 완전·앞부분 일치를 즉시로(#835).

정규형은 places.matching.normalize_name과 같은 규칙이다: 괄호 안·공백·기호를 지우고 소문자.
생성 열(STORED)이라 적재 코드가 쓰지 않고 이름이 바뀌면 따라 바뀐다. 기존 행은 열을 더할 때 채워진다.

Revision ID: 0044_places_name_norm
Revises: 0043_llm_calls
Create Date: 2026-10-31

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0044_places_name_norm"
down_revision: Union[str, None] = "0043_llm_calls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NORM = r"lower(regexp_replace(regexp_replace(name, '[(\[（][^)\]）]*[)\]）]', '', 'g'), '[^0-9a-zA-Z가-힣]', '', 'g'))"


def upgrade() -> None:
    op.execute(f"ALTER TABLE places ADD COLUMN name_norm text GENERATED ALWAYS AS ({_NORM}) STORED")
    op.execute("CREATE INDEX idx_places_name_norm ON places (name_norm text_pattern_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX idx_places_name_norm")
    op.execute("ALTER TABLE places DROP COLUMN name_norm")

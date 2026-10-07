"""#360 — 반응에서 △ 조율 필요(neutral)를 없앤다. reaction_type enum은 like|against 둘뿐.

배포 전이라 neutral 행은 마이그레이션에서 지운다(테스트 데이터뿐). 지운 사람의 반응 사유(근거 줄)는
recommend의 evidence_lines에 따로 남아 추천 근거로 계속 쓰인다. downgrade는 enum 값만 되살린다 —
지운 행은 돌아오지 않는다.
docs/data-model.md reactions, docs/CHANGELOG-api.md 2026-10-07(세 번째) 참고.

Revision ID: 0022_reaction_two_state
Revises: 0021_maps_delete_leave
Create Date: 2026-10-07

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0022_reaction_two_state"
down_revision: Union[str, None] = "0021_maps_delete_leave"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_enum(values: str) -> None:
    op.execute("ALTER TYPE reaction_type RENAME TO reaction_type_old")
    op.execute(f"CREATE TYPE reaction_type AS ENUM ({values})")
    op.execute("ALTER TABLE reactions ALTER COLUMN type TYPE reaction_type USING type::text::reaction_type")
    op.execute("DROP TYPE reaction_type_old")


def upgrade() -> None:
    op.execute("DELETE FROM reactions WHERE type = 'neutral'")
    _swap_enum("'like', 'against'")


def downgrade() -> None:
    _swap_enum("'like', 'neutral', 'against'")

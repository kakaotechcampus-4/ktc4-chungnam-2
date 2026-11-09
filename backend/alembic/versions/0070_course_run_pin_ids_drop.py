"""agent_course_runs.snapshot_pin_ids 삭제와 snapshot_version 기본값 제거 (#1465, 줄이기).

0067이 expand/contract에 맞춰 남겨 둔 옛 칸을 지운다. 이전 릴리스(v0.1.0, #1528)의 모델은 `snapshot_pin_ids`를 읽거나 쓰지 않고
`snapshot_version`을 넣으므로, 이 마이그레이션이 올라간 스키마에서도 돌아간다(`integration/test_schema_compat.py`가 본다).

- `snapshot_pin_ids`: 일정 version(`snapshot_version`)이 대신한다(#1321). 지워진 값은 downgrade로 돌아오지 않고 `[]`가 된다.
- `snapshot_version`의 기본값('legacy'): 새 코드가 늘 값을 넣는다. 0062 전 run은 이미 'legacy'로 채워졌다.
"""

from alembic import op

revision = "0070_course_run_pin_ids_drop"
down_revision = "0069_membership_last_seen_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_course_runs DROP COLUMN IF EXISTS snapshot_pin_ids")
    op.execute("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_version DROP DEFAULT")


def downgrade() -> None:
    # 0067 직후 모양: 칸은 기본값 '[]'로 돌아오고(값은 비었다), snapshot_version 기본값은 'legacy'다.
    op.execute("ALTER TABLE agent_course_runs ADD COLUMN IF NOT EXISTS snapshot_pin_ids JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_version SET DEFAULT 'legacy'")

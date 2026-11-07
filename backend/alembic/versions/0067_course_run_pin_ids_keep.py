"""agent_course_runs.snapshot_pin_ids를 줄이기 전까지 남긴다 (#1464, 멘토 리뷰).

처음 머지된 0062는 `snapshot_pin_ids`를 지우고 `snapshot_version`의 기본값도 지웠다. 이전 릴리스 코드는 `snapshot_pin_ids`를 읽고 쓰며
`snapshot_version`을 모른다. 그래서 배포 중이나 롤백 뒤에 AI 코스 조회와 생성이 깨진다. 0062는 늘리기만 하게 고쳤다.
이 마이그레이션은 어느 0062를 돌았든 같은 스키마로 맞춘다.

- 옛 0062를 돈 DB(스테이징, 로컬): 칸을 되살린다. 지워진 값은 돌아오지 않고 `[]`가 된다. 이전 코드는 그 run을 stale로 본다.
- 고친 0062를 돈 DB(운영): 칸과 값이 그대로다.
- 둘 다: 새 코드는 `snapshot_pin_ids`를 넣지 않으니 기본값 `'[]'`, 이전 코드는 `snapshot_version`을 넣지 않으니 기본값 'legacy'.

칸 삭제와 `snapshot_version` 기본값 제거는 #1465(운영에 새 코드가 올라간 다음 릴리스, deploy_rules.md 「지울 칸」).
"""

from alembic import op

revision = "0067_course_run_pin_ids_keep"
down_revision = "0065_recommend_run_radius_m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_course_runs ADD COLUMN IF NOT EXISTS snapshot_pin_ids JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_pin_ids SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_version SET DEFAULT 'legacy'")


def downgrade() -> None:
    # 고친 0062 직후 모양으로 돌아간다: snapshot_pin_ids는 0037처럼 기본값이 없고, snapshot_version 기본값은 0062 것이다.
    op.execute("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_pin_ids DROP DEFAULT")

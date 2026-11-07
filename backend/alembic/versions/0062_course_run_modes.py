"""agent_course_runs — 일정 기준 모드의 결과 칸과 일정 version 스냅샷 (#1321, 결정 #1237).

- `mode`(plan|fill|review): 요청 때 서버가 확정 리스트의 일정 상태로 정한다. 기존 run은 모두 plan이다(그때는 일정을 읽지 않았다).
- `headline`, `fixes`, `checked`: 결과 화면의 머리 문구, 고칠 점 카드, 점검 통과 항목. 기존 run은 비어 있다.
- `snapshot_version`이 `snapshot_pin_ids`(핀 id 목록)를 대신한다. 일정 version에 확정 장소 집합·날짜 배정·순서·여행 기간이 들어 있어
  stale 판정이 version 하나로 줄어든다. 기존 run은 옛 값을 version으로 바꿀 수 없어 'legacy'로 두고, 지금 version과 다르니 stale=true로 보인다
  (이전 코스를 일정 기준으로 다시 믿을 수 없다 — 「다시 짜기」를 안내한다).

늘리기만 한다(expand, deploy_rules.md 「스키마를 바꿀 때」). 이전 코드가 읽고 쓰는 `snapshot_pin_ids`는 남기고, 이전 코드가 넣지 않는
`snapshot_version`은 기본값 'legacy'를 둔다. 처음 머지된 이 파일은 칸 삭제와 기본값 제거까지 같이 해서 이전 코드가 깨졌다(멘토 리뷰, #1464).
운영이 돌기 전에 고쳤고, 옛 내용을 이미 돈 DB(스테이징, 로컬)는 0067이 맞춘다. 칸 삭제는 #1465(다음 릴리스).

Revision ID: 0062_course_run_modes
Revises: 0061_recommend_run_origin
Create Date: 2026-11-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062_course_run_modes"
down_revision: Union[str, None] = "0061_recommend_run_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column("agent_course_runs", sa.Column("mode", sa.String(), server_default="plan", nullable=False))
    op.add_column("agent_course_runs", sa.Column("headline", sa.String(), nullable=True))
    op.add_column("agent_course_runs", sa.Column("fixes", postgresql.JSONB(), server_default=_EMPTY, nullable=False))
    op.add_column("agent_course_runs", sa.Column("checked", postgresql.JSONB(), server_default=_EMPTY, nullable=False))
    op.add_column("agent_course_runs", sa.Column("snapshot_version", sa.String(), server_default="legacy", nullable=False))


def downgrade() -> None:
    for column in ("snapshot_version", "checked", "fixes", "headline", "mode"):
        op.drop_column("agent_course_runs", column)

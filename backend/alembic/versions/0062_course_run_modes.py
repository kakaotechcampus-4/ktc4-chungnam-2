"""agent_course_runs — 일정 기준 모드의 결과 칸과 일정 version 스냅샷 (#1321, 결정 #1237).

- `mode`(plan|fill|review): 요청 때 서버가 확정 리스트의 일정 상태로 정한다. 기존 run은 모두 plan이다(그때는 일정을 읽지 않았다).
- `headline`, `fixes`, `checked`: 결과 화면의 머리 문구, 고칠 점 카드, 점검 통과 항목. 기존 run은 비어 있다.
- `snapshot_version`이 `snapshot_pin_ids`(핀 id 목록)를 대신한다. 일정 version에 확정 장소 집합·날짜 배정·순서·여행 기간이 들어 있어
  stale 판정이 version 하나로 줄어든다. 기존 run은 옛 값을 version으로 바꿀 수 없어 'legacy'로 두고, 지금 version과 다르니 stale=true로 보인다
  (이전 코스를 일정 기준으로 다시 믿을 수 없다 — 「다시 짜기」를 안내한다). 내리면 핀 id 목록은 빈 배열로 돌아온다.

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
    op.alter_column("agent_course_runs", "snapshot_version", server_default=None)
    op.drop_column("agent_course_runs", "snapshot_pin_ids")


def downgrade() -> None:
    op.add_column("agent_course_runs", sa.Column("snapshot_pin_ids", postgresql.JSONB(), server_default=_EMPTY, nullable=False))
    op.alter_column("agent_course_runs", "snapshot_pin_ids", server_default=None)
    for column in ("snapshot_version", "checked", "fixes", "headline", "mode"):
        op.drop_column("agent_course_runs", column)

"""#976 — agent_course_runs의 ix_agent_course_runs_user_created(requested_by, created_at) 삭제.

코스 하루 상한(사용자당 5회)을 세려고 0037에서 만든 인덱스다. 하루 상한은 #950에서 크레딧으로 바뀌어 이 인덱스를 쓰는 쿼리가
없다. ix_agent_course_runs_map_user(진행 중 run 찾기)와 uq_agent_course_runs_active는 그대로 둔다.

downgrade는 0037과 같은 모양으로 다시 만든다.

Revision ID: 0050_drop_course_user_index
Revises: 0049_reviews
Create Date: 2026-11-01

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0050_drop_course_user_index"
down_revision: Union[str, None] = "0049_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_agent_course_runs_user_created", table_name="agent_course_runs")


def downgrade() -> None:
    op.create_index("ix_agent_course_runs_user_created", "agent_course_runs", ["requested_by", "created_at"])

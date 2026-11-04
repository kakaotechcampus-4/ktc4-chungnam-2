"""agent_suggestions에 후속 관찰 칸 셋 — attempt, followup_of, followup (#1346, 결정 #1345, docs/agent-v2.md 6.9).

칸을 더하기만 한다(expand). 이전 서버의 INSERT는 attempt 기본값 0, 나머지 NULL로 그대로 돈다. 사용자 id 열이 아니라
게스트 합치기·탈퇴 목록은 그대로다.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0063_agent_suggestion_followup"
down_revision = "0062_course_run_modes"   # 번호가 겹쳐 먼저 병합된 0062(course) 뒤로 옮겼다(#1347)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_suggestions", sa.Column("attempt", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("agent_suggestions", sa.Column("followup_of", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("agent_suggestions", sa.Column("followup", postgresql.JSONB(), nullable=True))
    op.create_foreign_key(
        "agent_suggestions_followup_of_fkey", "agent_suggestions", "agent_suggestions", ["followup_of"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("agent_suggestions_followup_of_fkey", "agent_suggestions", type_="foreignkey")
    op.drop_column("agent_suggestions", "followup")
    op.drop_column("agent_suggestions", "followup_of")
    op.drop_column("agent_suggestions", "attempt")

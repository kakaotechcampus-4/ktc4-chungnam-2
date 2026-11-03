"""agent_run_advice에 state_key 칸을 더한다 (#1103).

넓히기·다시 추천은 같은 run id로 결과를 바꾸는데 조언이 run마다 한 번만 저장돼 첫 결과의 빈 조언이 남았다. 조언 행에 만든 결과 상태
(state_key)를 남기고, 결과가 바뀌면 같은 행을 새 조언으로 덮는다. expand만 한다 — 칸 하나(기본 '')를 더하고 기본키는 run_id 그대로라
이전 서버의 `ON CONFLICT (run_id) DO NOTHING`도 새 스키마에서 돈다(deploy_rules.md 스키마를 바꿀 때). 기존 행은 빈 키라 어떤 결과 상태와도
달라 다음 조회에 한 번 다시 만든다(조언은 코드가 만들고 모델이 없어 비용이 없다).

Revision ID: 0057_agent_advice_state_key
Revises: 0056_agent_map_status_facts
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_agent_advice_state_key"
down_revision: Union[str, None] = "0056_agent_map_status_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_run_advice", sa.Column("state_key", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("agent_run_advice", "state_key")

"""agent_run_advice에 state_key를 더하고 기본키를 (run_id, state_key)로 바꾼다 (#1103).

넓히기·다시 추천은 같은 run id로 결과를 바꾸는데 조언이 run마다 한 번만 저장돼 첫 결과의 빈 조언이 남았다. 조언을 결과 상태마다
저장한다. 기존 행은 state_key=''로 남고 어떤 결과 상태 키와도 같지 않아 다음 조회에 한 번 다시 만든다(조언은 코드가 만들고 모델이
없어 비용이 없다).

Revision ID: 0056_agent_advice_state_key
Revises: 0055_place_external_ids
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_agent_advice_state_key"
down_revision: Union[str, None] = "0055_place_external_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_run_advice", sa.Column("state_key", sa.String(), nullable=False, server_default=""))
    op.drop_constraint("agent_run_advice_pkey", "agent_run_advice", type_="primary")
    op.create_primary_key("agent_run_advice_pkey", "agent_run_advice", ["run_id", "state_key"])


def downgrade() -> None:
    # 한 run에 행이 여럿이면 가장 늦게 만든 것만 남긴다.
    op.execute(
        "DELETE FROM agent_run_advice a USING agent_run_advice b "
        "WHERE a.run_id = b.run_id AND (a.created_at, a.state_key) < (b.created_at, b.state_key)"
    )
    op.drop_constraint("agent_run_advice_pkey", "agent_run_advice", type_="primary")
    op.create_primary_key("agent_run_advice_pkey", "agent_run_advice", ["run_id"])
    op.drop_column("agent_run_advice", "state_key")

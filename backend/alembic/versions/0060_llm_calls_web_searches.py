"""llm_calls.web_searches — 웹 확인(agent-v2 6.8)의 웹 검색 횟수 (#1216, 결정 #1152 ④).

모델 호출 1건 안의 웹 검색 횟수(Responses 응답의 web_search_call 수)다. 검색 요금(web_searches × LLM_PRICE_WEB_SEARCH_KRW)은
cost_krw에 이미 더해 남기고, 이 열은 OpenAI 대시보드의 web search 줄과 대조하려고 둔다. 기본값 있는 열이라 기존 행은 0이다(expand).
feature·call의 agent_web_check는 text라 마이그레이션이 없다.

Revision ID: 0060_llm_calls_web_searches
Revises: 0059_shortlist_scheduled_date
Create Date: 2026-11-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_llm_calls_web_searches"
down_revision: Union[str, None] = "0059_shortlist_scheduled_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("web_searches", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("llm_calls", "web_searches")

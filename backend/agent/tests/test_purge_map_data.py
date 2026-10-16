"""api.purge_map_data(#431, 명세 17절 16번) — 대상 지도의 agent_* 7개 테이블 행만 지운다."""

from sqlalchemy import func, select

from agent import api
from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)
from agent.tests import rows

TABLES = {
    "agent_suggestion_views": AgentSuggestionView,
    "agent_suggestions": AgentSuggestion,
    "agent_run_advice": AgentRunAdvice,
    "agent_reason_summaries": AgentReasonSummary,
    "agent_runs": AgentRun,
    "agent_cursors": AgentCursor,
    "agent_settings": AgentSettings,
}


def _count(db, model):
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_purge_deletes_every_agent_row_of_target_maps_only(db_session):
    rows.fill_map(db_session, "gone1")
    rows.fill_map(db_session, "gone2")
    rows.fill_map(db_session, "keep")

    result = api.purge_map_data(db_session, map_ids=["gone1", "gone2"])

    assert result == {
        "agent_suggestion_views": 4, "agent_suggestions": 2, "agent_run_advice": 2, "agent_reason_summaries": 2,
        "agent_runs": 2, "agent_cursors": 2, "agent_settings": 2,
    }
    # 남은 것은 keep 지도 몫뿐이다(열람 2, 나머지 1씩)
    assert {name: _count(db_session, model) for name, model in TABLES.items()} == {
        name: (2 if name == "agent_suggestion_views" else 1) for name in TABLES
    }
    assert db_session.execute(select(AgentRun.map_id)).scalars().all() == ["keep"]


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    rows.fill_map(db_session, "keep")

    assert api.purge_map_data(db_session, map_ids=[]) == dict.fromkeys(TABLES, 0)
    assert _count(db_session, AgentRun) == 1

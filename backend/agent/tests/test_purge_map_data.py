"""api.purge_map_data(#431, 명세 17절 16번) — 대상 지도의 agent_* 7개 테이블 행만 지운다.

같은 DB에 다른 테스트가 커밋한 agent 행이 있어도 흔들리지 않게, 테스트마다 자기만 쓰는 지도 id로 행을 만들고 그
지도의 행만 센다(#594).
"""

import uuid

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


def _map_ids(*names):
    prefix = f"purge{uuid.uuid4().hex[:6]}"
    return [f"{prefix}_{name}" for name in names]


def _count(db, model, map_ids):
    stmt = select(func.count()).select_from(model)
    if model is AgentSuggestionView:   # 열람은 map_id가 없다 — 제안을 거쳐 지도를 본다
        stmt = stmt.join(AgentSuggestion, AgentSuggestion.id == AgentSuggestionView.suggestion_id)
        return db.execute(stmt.where(AgentSuggestion.map_id.in_(map_ids))).scalar_one()
    return db.execute(stmt.where(model.map_id.in_(map_ids))).scalar_one()


def test_purge_deletes_every_agent_row_of_target_maps_only(db_session):
    gone1, gone2, keep = mine = _map_ids("gone1", "gone2", "keep")
    for map_id in mine:
        rows.fill_map(db_session, map_id)

    result = api.purge_map_data(db_session, map_ids=[gone1, gone2])

    assert result == {
        "agent_suggestion_views": 4, "agent_suggestions": 2, "agent_run_advice": 2, "agent_reason_summaries": 2,
        "agent_runs": 2, "agent_cursors": 2, "agent_settings": 2,
    }
    # 남은 것은 keep 지도 몫뿐이다(열람 2, 나머지 1씩)
    assert {name: _count(db_session, model, mine) for name, model in TABLES.items()} == {
        name: (2 if name == "agent_suggestion_views" else 1) for name in TABLES
    }
    assert db_session.execute(select(AgentRun.map_id).where(AgentRun.map_id.in_(mine))).scalars().all() == [keep]


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    mine = _map_ids("keep")
    rows.fill_map(db_session, mine[0])

    assert api.purge_map_data(db_session, map_ids=[]) == dict.fromkeys(TABLES, 0)
    assert _count(db_session, AgentRun, mine) == 1

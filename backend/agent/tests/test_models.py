"""테이블 제약 — 지도당 활성 제안 하나(부분 유니크 인덱스, 명세 17절 8번), FK 동작, 기본값."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agent.models import AgentRun, AgentSuggestion, AgentSuggestionView
from agent.tests import rows


def test_second_active_suggestion_on_same_map_is_rejected(db_session):
    rows.suggestion(db_session, "m1")
    with pytest.raises(IntegrityError) as exc:
        rows.suggestion(db_session, "m1")
    assert "uq_agent_suggestions_active" in str(exc.value)


def test_active_is_unique_per_map_only_and_resolved_ones_do_not_count(db_session):
    rows.suggestion(db_session, "m1", status="dismissed")
    rows.suggestion(db_session, "m1", status="superseded")
    rows.suggestion(db_session, "m1")
    rows.suggestion(db_session, "m2")  # 다른 지도는 따로 하나씩

    actives = db_session.execute(select(AgentSuggestion.map_id).where(AgentSuggestion.status == "active")).scalars()
    assert sorted(actives) == ["m1", "m2"]


def test_resolving_active_frees_the_slot(db_session):
    first = rows.suggestion(db_session, "m1")
    first.status = "expired"
    db_session.flush()
    rows.suggestion(db_session, "m1")


def test_deleting_run_keeps_suggestion_and_deleting_suggestion_drops_views(db_session):
    r = rows.run(db_session, "m1")
    s = rows.suggestion(db_session, "m1", run_id=r.id)
    rows.view(db_session, s.id, "u1")

    db_session.delete(r)
    db_session.flush()
    db_session.refresh(s)
    assert s.run_id is None  # ON DELETE SET NULL

    db_session.delete(s)
    db_session.flush()
    assert db_session.execute(select(AgentSuggestionView)).first() is None  # ON DELETE CASCADE


def test_run_defaults(db_session):
    r = rows.run(db_session, "m1")
    db_session.expire(r)
    r = db_session.get(AgentRun, r.id)
    assert (r.signals, r.blocked, r.tool_calls) == ([], [], [])
    assert (r.used_model, r.tokens_in, r.tokens_out) == (False, 0, 0)
    assert r.verification is None and r.priority is None

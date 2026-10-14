"""테스트용 agent_* 행 만들기. 필수 칸만 채우고 나머지는 키워드로 바꾼다."""

import uuid
from datetime import datetime, timedelta, timezone

from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def add(db, row):
    db.add(row)
    db.flush()
    return row


def run(db, map_id, **kw):
    fields = {"map_id": map_id, "started_at": NOW, "trigger": "activity", "outcome": "no_signal"} | kw
    return add(db, AgentRun(**fields))


def suggestion(db, map_id, *, run_id=None, status="active", **kw):
    fields = {
        "map_id": map_id, "run_id": run_id, "diagnosis": "category_gap", "category": "카페",
        "fingerprint": f"fp-{uuid.uuid4()}", "evidence_hash": "eh", "title": "확정 리스트에 카페가 아직 없어요",
        "claims": [], "advice": [], "actions": [], "status": status, "expires_at": NOW + timedelta(hours=24),
    } | kw
    return add(db, AgentSuggestion(**fields))


def view(db, suggestion_id, user_id):
    return add(db, AgentSuggestionView(suggestion_id=suggestion_id, user_id=user_id))


def summary(db, map_id, category="음식점", **kw):
    fields = {"map_id": map_id, "category": category, "summary": {"must_keep": []}, "based_on_reaction_count": 3} | kw
    return add(db, AgentReasonSummary(**fields))


def advice(db, map_id, **kw):
    fields = {"run_id": uuid.uuid4(), "map_id": map_id, "claims": [], "advice": [], "actions": []} | kw
    return add(db, AgentRunAdvice(**fields))


def cursor(db, map_id):
    return add(db, AgentCursor(map_id=map_id))


def settings(db, map_id, enabled=True):
    return add(db, AgentSettings(map_id=map_id, enabled=enabled, updated_by="u1"))


def fill_map(db, map_id):
    """한 지도에 agent_* 7개 테이블 행을 하나씩 넣는다(열람은 둘)."""
    r = run(db, map_id)
    s = suggestion(db, map_id, run_id=r.id)
    view(db, s.id, "u1")
    view(db, s.id, "u2")
    summary(db, map_id)
    advice(db, map_id)
    cursor(db, map_id)
    settings(db, map_id)

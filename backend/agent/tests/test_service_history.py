"""service.load_history(#515) — 정책이 보는 이력 모양(core.History)과 오늘 모델 사용 수(12.3)."""

from datetime import timedelta

from agent import core, service
from agent.tests import rows
from agent.tests.rows import NOW


def test_history_is_newest_first_with_evidence_hash(db_session):
    old = rows.suggestion(db_session, "map_1", status="dismissed", created_at=NOW - timedelta(hours=5),
                          evidence_hash="eh-old")
    new = rows.suggestion(db_session, "map_1", status="active", created_at=NOW - timedelta(hours=1),
                          evidence_hash="eh-new")
    rows.suggestion(db_session, "map_2", status="active")

    hist = service.load_history(db_session, "map_1", NOW)

    assert [h.id for h in hist.suggestions] == [str(new.id), str(old.id)]
    assert hist.active.evidence_hash == "eh-new"


def test_model_runs_today_counts_model_runs_since_kst_midnight(db_session):
    day_start = core.kst_day_start(NOW)
    rows.run(db_session, "map_1", used_model=True, trigger="activity", started_at=day_start)
    rows.run(db_session, "map_1", used_model=True, trigger="summary", started_at=day_start + timedelta(hours=1))
    rows.run(db_session, "map_1", used_model=True, trigger="run_advice", started_at=day_start)   # 상한 밖
    rows.run(db_session, "map_1", used_model=False, trigger="time", started_at=day_start)
    rows.run(db_session, "map_1", used_model=True, trigger="time", started_at=day_start - timedelta(seconds=1))
    rows.run(db_session, "map_2", used_model=True, trigger="time", started_at=day_start)

    assert service.load_history(db_session, "map_1", NOW).model_runs_today == 2

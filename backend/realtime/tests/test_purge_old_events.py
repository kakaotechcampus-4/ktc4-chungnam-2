"""api.purge_old_events(#1016) — 25시간 지난 event_log만 지운다. 실제 DB."""

from datetime import datetime, timedelta, timezone

from common.events import EventLog
from realtime import api, service

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _event(db, age_hours, map_id="m", now=NOW):
    row = EventLog(map_id=map_id, channel="public", type="pin.created", payload={}, created_at=now - timedelta(hours=age_hours))
    db.add(row)
    db.flush()
    return row


def test_deletes_rows_older_than_25_hours_and_keeps_the_rest(db_session):
    old = _event(db_session, 25.01)
    edge = _event(db_session, 25)      # 정확히 25시간 — created_at < 기준이 아니라서 남는다
    inside_window = _event(db_session, 23)

    assert api.purge_old_events(db_session, now=NOW) == 1
    assert {r.seq for r in db_session.query(EventLog).all()} == {edge.seq, inside_window.seq}
    assert old.seq not in {r.seq for r in db_session.query(EventLog).all()}


def test_is_idempotent(db_session):
    _event(db_session, 30)
    assert api.purge_old_events(db_session, now=NOW) == 1
    assert api.purge_old_events(db_session, now=NOW) == 0


def test_batch_limit_deletes_oldest_first_and_next_run_continues(db_session, monkeypatch):
    monkeypatch.setattr(service, "PURGE_BATCH", 2)
    oldest = _event(db_session, 50)
    second = _event(db_session, 40)
    third = _event(db_session, 30)

    assert api.purge_old_events(db_session, now=NOW) == 2
    assert [r.seq for r in db_session.query(EventLog).all()] == [third.seq]
    assert api.purge_old_events(db_session, now=NOW) == 1
    assert db_session.query(EventLog).count() == 0
    assert oldest.seq < second.seq < third.seq


def test_rows_inside_replay_window_survive_and_still_replay(db_session):
    real = datetime.now(timezone.utc)
    fresh = _event(db_session, 1, map_id="rp", now=real)
    api.purge_old_events(db_session, now=real)
    result = service.replay(db_session, "rp", fresh.seq - 1, "public")
    assert [r.seq for r in result.rows] == [fresh.seq] and not result.truncated


def test_last_event_id_pointing_at_purged_seq_is_truncated(db_session):
    """25시간 지난 행이 지워진 뒤 그 seq로 재연결하면 기존 replay_truncated 경로로 간다."""
    real = datetime.now(timezone.utc)
    gone = _event(db_session, 30, map_id="rt", now=real)
    kept = _event(db_session, 1, map_id="rt", now=real)
    api.purge_old_events(db_session, now=real)

    # 클라이언트가 지워진 행 앞의 seq까지만 본 상태 — 그 사이 구간이 사라졌으니 잘림으로 알린다.
    result = service.replay(db_session, "rt", gone.seq - 1, "public")

    assert result.truncated
    assert [r.seq for r in result.rows] == [kept.seq]

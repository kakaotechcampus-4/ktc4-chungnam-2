"""service.py::replay — 실제 PostgreSQL 필요(docker-compose up -d)."""

from datetime import datetime, timedelta, timezone

from common.events import EventLog
from realtime.service import RETENTION, replay


def _row(db, map_id="map1", channel="public", created_at=None, recipient_user_id=None):
    row = EventLog(
        map_id=map_id, channel=channel, type="pin.created", payload={"x": 1},
        recipient_user_id=recipient_user_id,
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.flush()
    return row


def test_replay_returns_rows_after_seq_for_matching_channel_and_map(db_session):
    r1 = _row(db_session)
    r2 = _row(db_session)
    r3 = _row(db_session)
    _row(db_session, map_id="other-map")
    _row(db_session, channel="private", recipient_user_id="u1")

    result = replay(db_session, "map1", after_seq=r1.seq, channel="public")

    assert [r.seq for r in result.rows] == [r2.seq, r3.seq]
    assert result.truncated is False


def test_replay_empty_when_no_new_rows(db_session):
    r1 = _row(db_session)

    result = replay(db_session, "map1", after_seq=r1.seq + 998, channel="public")

    assert result.rows == []
    assert result.truncated is False


def test_replay_not_truncated_when_no_rows_at_all(db_session):
    result = replay(db_session, "map1", after_seq=0, channel="public")

    assert result.rows == []
    assert result.truncated is False


def test_replay_truncated_when_after_seq_predates_retention_window(db_session):
    now = datetime.now(timezone.utc)
    old_row = _row(db_session, created_at=now - RETENTION - timedelta(hours=1))
    recent_row = _row(db_session, created_at=now - timedelta(hours=1))

    result = replay(db_session, "map1", after_seq=old_row.seq - 1, channel="public")

    assert result.truncated is True
    assert [r.seq for r in result.rows] == [recent_row.seq]


def test_replay_not_truncated_when_after_seq_is_exactly_the_boundary(db_session):
    now = datetime.now(timezone.utc)
    old_row = _row(db_session, created_at=now - RETENTION - timedelta(hours=1))
    recent_row = _row(db_session, created_at=now - timedelta(hours=1))

    result = replay(db_session, "map1", after_seq=old_row.seq, channel="public")

    assert result.truncated is False
    assert [r.seq for r in result.rows] == [recent_row.seq]

"""realtime.api.latest_seq_by_map(#522, #525) — agent claim_maps가 쓰는 지도별 가장 큰 event_log seq와 그 created_at."""

from datetime import datetime, timedelta, timezone

from common.events import EventLog
from realtime import api
from realtime.service import RETENTION


def _event(db, map_id, *, channel="public", recipient=None, created_at=None):
    row = EventLog(map_id=map_id, channel=channel, type="pin.created", payload={}, recipient_user_id=recipient)
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.flush()
    return row


def test_returns_largest_seq_and_its_created_at_per_map(db_session):
    now = datetime.now(timezone.utc)
    _event(db_session, "map_1", created_at=now - timedelta(minutes=3))
    last = _event(db_session, "map_1", channel="private", recipient="u1", created_at=now - timedelta(minutes=1))

    assert api.latest_seq_by_map(db_session) == {"map_1": (last.seq, last.created_at)}


def test_maps_do_not_mix(db_session):
    now = datetime.now(timezone.utc)
    a1 = _event(db_session, "map_a", created_at=now - timedelta(minutes=5))
    b1 = _event(db_session, "map_b", created_at=now - timedelta(minutes=4))
    b2 = _event(db_session, "map_b", created_at=now - timedelta(minutes=2))

    result = api.latest_seq_by_map(db_session)

    assert result == {"map_a": (a1.seq, a1.created_at), "map_b": (b2.seq, b2.created_at)}
    assert b1.seq > a1.seq   # map_a의 최대 seq는 다른 지도의 더 큰 seq에 끌려가지 않는다


def test_rows_outside_retention_are_excluded(db_session):
    now = datetime.now(timezone.utc)
    _event(db_session, "old_map", created_at=now - RETENTION - timedelta(hours=1))
    recent = _event(db_session, "map_1", created_at=now - timedelta(hours=1))
    # seq는 더 크지만 보존기간 밖인 행 — 필터가 없으면 이 행이 최대로 잡힌다
    _event(db_session, "map_1", created_at=now - RETENTION - timedelta(hours=1))

    assert api.latest_seq_by_map(db_session) == {"map_1": (recent.seq, recent.created_at)}


def test_map_without_events_has_no_key(db_session):
    _event(db_session, "map_1")

    result = api.latest_seq_by_map(db_session)

    assert "no_events" not in result
    assert set(result) == {"map_1"}


def test_empty_log_returns_empty_dict(db_session):
    assert api.latest_seq_by_map(db_session) == {}

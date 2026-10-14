"""api.purge_map_data(#431) — 대상 지도의 event_log(공개·개인 채널 모두)만 지운다."""

from common.events import EventLog
from realtime import api


def _event(db, map_id, channel="public", recipient=None):
    db.add(EventLog(map_id=map_id, channel=channel, type="pin.created", payload={}, recipient_user_id=recipient))
    db.flush()


def test_purge_deletes_only_target_maps_events(db_session):
    _event(db_session, "gone")
    _event(db_session, "gone", channel="private", recipient="u1")
    _event(db_session, "keep")

    result = api.purge_map_data(db_session, map_ids=["gone"])

    assert result == {"event_log": 2}
    assert [row.map_id for row in db_session.query(EventLog).all()] == ["keep"]


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    _event(db_session, "keep")

    assert api.purge_map_data(db_session, map_ids=[]) == {"event_log": 0}
    assert db_session.query(EventLog).count() == 1

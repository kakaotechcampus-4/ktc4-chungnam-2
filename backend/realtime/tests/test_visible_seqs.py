"""realtime.api.visible_seqs(#522) — agent 커서가 쓰는 이 지도의 event_log seq 목록. 번호만 돌려준다."""

from common.events import EventLog
from realtime import api


def _event(db, map_id, channel="public", recipient=None):
    row = EventLog(map_id=map_id, channel=channel, type="pin.created", payload={}, recipient_user_id=recipient)
    db.add(row)
    db.flush()
    return row.seq


def test_returns_this_maps_seqs_after_cursor_ascending(db_session):
    first = _event(db_session, "map_1")
    other = _event(db_session, "other_map")
    private = _event(db_session, "map_1", channel="private", recipient="u1")
    last = _event(db_session, "map_1")

    assert api.visible_seqs(db_session, map_id="map_1", after_seq=0) == [first, private, last]
    assert api.visible_seqs(db_session, map_id="map_1", after_seq=first) == [private, last]
    assert other not in api.visible_seqs(db_session, map_id="map_1", after_seq=0)


def test_nothing_after_cursor_returns_empty(db_session):
    last = _event(db_session, "map_1")

    assert api.visible_seqs(db_session, map_id="map_1", after_seq=last) == []
    assert api.visible_seqs(db_session, map_id="no_events", after_seq=0) == []

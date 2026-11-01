"""Event.payload는 객체뿐 아니라 배열도 싣는다 — route.recalculated는 Route[]다(docs/events.md, #768).

DB 없이 JSONB 열이 두 모양을 모두 직렬화하는지 본다(common에는 DB fixture를 따로 두지 않는다)."""

import json

import pytest
from sqlalchemy.dialects import postgresql

from common.events import Event, EventLog


def _serialize(value):
    dialect = postgresql.dialect()
    column_type = EventLog.__table__.c.payload.type
    return column_type.dialect_impl(dialect).bind_processor(dialect)(value)


@pytest.mark.parametrize("payload", [
    [{"day": 1, "stops": ["a", "b"]}, {"day": 2, "stops": []}],
    [],
    {"map_id": "m1"},
])
def test_payload_column_round_trips_list_and_dict(payload):
    assert json.loads(_serialize(payload)) == payload


def test_event_accepts_a_list_payload():
    event = Event(map_id="m1", channel="public", type="route.recalculated", payload=[{"day": 1}])

    assert event.payload == [{"day": 1}]

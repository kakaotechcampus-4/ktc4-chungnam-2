"""shortlist.api.list_items_for_agent(#522) — agent 스냅샷이 읽는 확정 항목. 읽기만 한다."""

from datetime import datetime, timedelta, timezone

from pins.models import Pin
from shortlist import api
from shortlist.models import ShortlistItem

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _confirm(db, map_id, *, added_by, minutes):
    pin = Pin(
        map_id=map_id, category="음식점", kind="확정", origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}_{minutes}", search_query="맛집", visibility="public", created_by="u1",
    )
    db.add(pin)
    db.flush()
    db.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by=added_by, added_at=T0 + timedelta(minutes=minutes)))
    db.flush()
    return str(pin.id)


def test_returns_pin_adder_and_time_in_added_order(db_session):
    later = _confirm(db_session, "map_1", added_by="u2", minutes=10)
    earlier = _confirm(db_session, "map_1", added_by="u1", minutes=0)
    _confirm(db_session, "other_map", added_by="u1", minutes=5)

    assert api.list_items_for_agent(db_session, map_id="map_1") == [
        {"pin_id": earlier, "added_by": "u1", "added_at": T0},
        {"pin_id": later, "added_by": "u2", "added_at": T0 + timedelta(minutes=10)},
    ]


def test_empty_map_returns_empty_list(db_session):
    assert api.list_items_for_agent(db_session, map_id="map_1") == []

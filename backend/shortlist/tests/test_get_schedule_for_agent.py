"""shortlist.api.get_schedule_for_agent(#1238) — AI 코스가 읽는 일정. 읽기만 한다."""

from datetime import date, datetime, timedelta, timezone

import pytest

from common.errors import AppError
from maps.models import Map
from pins.models import Pin
from shortlist import api, service
from shortlist.models import ShortlistItem

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
START, END = date(2026, 11, 12), date(2026, 11, 15)


def _map(db, map_id="map_1"):
    db.add(Map(id=map_id, title="t", start_date=START, end_date=END, created_by="u1"))
    db.flush()


def _item(db, map_id, n, *, day=None, order=None):
    pin = Pin(
        map_id=map_id, category="음식점", kind="확정", origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}_{n}", search_query="맛집", visibility="public", created_by="u1",
    )
    db.add(pin)
    db.flush()
    db.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by="u1", added_at=T0 + timedelta(minutes=n),
                         scheduled_date=day, visit_order=order))
    db.flush()
    return str(pin.id)


def test_unassigned_items_have_none_and_come_last(db_session):
    _map(db_session)
    unassigned = _item(db_session, "map_1", 0)
    scheduled = _item(db_session, "map_1", 5, day=START, order=0)

    result = api.get_schedule_for_agent(db_session, map_id="map_1")

    assert (result["start_date"], result["end_date"]) == (START, END)
    assert [(i["pin_id"], i["scheduled_date"], i["visit_order"]) for i in result["items"]] == [
        (scheduled, START, 0),
        (unassigned, None, None),
    ]


def test_order_within_a_day_follows_visit_order(db_session):
    _map(db_session)
    second = _item(db_session, "map_1", 0, day=START, order=1)
    first = _item(db_session, "map_1", 9, day=START, order=0)
    next_day = _item(db_session, "map_1", 1, day=START + timedelta(days=1), order=0)

    items = api.get_schedule_for_agent(db_session, map_id="map_1")["items"]

    assert [i["pin_id"] for i in items] == [first, second, next_day]
    assert items[0]["added_by"] == "u1" and items[0]["added_at"] == T0 + timedelta(minutes=9)


def test_version_matches_schedule_endpoint_rule(db_session):
    _map(db_session)
    _item(db_session, "map_1", 0, day=START, order=0)
    _item(db_session, "map_1", 1)

    result = api.get_schedule_for_agent(db_session, map_id="map_1")

    rows = service.list_items(db_session, map_id="map_1")
    assert result["version"] == service.schedule_version(START, END, rows)
    assert [i["pin_id"] for i in result["items"]] == [str(r.pin_id) for r in rows]


def test_missing_map_is_not_found(db_session):
    with pytest.raises(AppError) as exc:
        api.get_schedule_for_agent(db_session, map_id="nope")
    assert exc.value.code == "NOT_FOUND"

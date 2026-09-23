"""shortlist/api.py — 다른 모듈이 부르는 교차 모듈 접점 테스트. 실제 PostgreSQL 필요(conftest.py)."""

import uuid

from sqlalchemy import func

from pins.models import Pin as PinRow
from shortlist import api, service


def _insert_pin(db_session, *, map_id="map_1"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_count_confirmed_is_zero_for_map_with_no_items(db_session):
    assert api.count_confirmed(db_session, map_id="map_with_nothing") == 0


def test_count_confirmed_counts_only_the_given_map(db_session):
    pin_1 = _insert_pin(db_session, map_id="map_1")
    pin_2 = _insert_pin(db_session, map_id="map_1")
    other_map_pin = _insert_pin(db_session, map_id="map_2")
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_1.id), added_by="user_1")
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_2.id), added_by="user_1")
    service.add_item(db_session, map_id="map_2", pin_id=str(other_map_pin.id), added_by="user_1")

    assert api.count_confirmed(db_session, map_id="map_1") == 2
    assert api.count_confirmed(db_session, map_id="map_2") == 1


def test_count_confirmed_decreases_after_removal(db_session):
    pin = _insert_pin(db_session, map_id="map_1")
    row, _ = service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_1")
    assert api.count_confirmed(db_session, map_id="map_1") == 1

    service.delete_item(db_session, item_id=str(row.id))

    assert api.count_confirmed(db_session, map_id="map_1") == 0

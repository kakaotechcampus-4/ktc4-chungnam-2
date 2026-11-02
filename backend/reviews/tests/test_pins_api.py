"""pins.api.has_place_pin_on_member_map(#951에서 더함) — 신고할 수 있는 사람(그 후기를 볼 수 있는 사람)의 판정.

함수는 pins.api에 있지만 부르는 곳이 reviews 하나라 여기서 본다.
"""

import uuid

from sqlalchemy import func

from maps.models import Map
from pins import api as pins_api
from pins.models import Pin


def test_member_of_a_map_with_that_place_pin(world):
    a, b, outsider = world.user("a"), world.user("b"), world.user("outsider")
    place_id = world.place()
    world.pin(world.map(a, b), place_id, by=a)

    assert pins_api.has_place_pin_on_member_map(world.db, user_id=b, place_id=place_id) is True
    assert pins_api.has_place_pin_on_member_map(world.db, user_id=outsider, place_id=place_id) is False
    assert pins_api.has_place_pin_on_member_map(world.db, user_id=a, place_id=world.place("다른 가게")) is False


def test_any_of_several_maps_is_enough(world):
    a, c = world.user("a"), world.user("c")
    place_id = world.place()
    world.pin(world.map(a), place_id, by=a)
    world.pin(world.map(c), place_id, by=c)

    assert pins_api.has_place_pin_on_member_map(world.db, user_id=c, place_id=place_id) is True


def test_deleted_pin_or_deleted_map_does_not_count(world):
    a = world.user("a")
    place_id = world.place()
    map_id = world.map(a)
    pin_id = world.pin(map_id, place_id, by=a)

    world.db.get(Pin, uuid.UUID(pin_id)).deleted_at = func.now()
    world.db.flush()
    assert pins_api.has_place_pin_on_member_map(world.db, user_id=a, place_id=place_id) is False

    other_map = world.map(a)
    world.pin(other_map, place_id, by=a)
    world.db.get(Map, other_map).deleted_at = func.now()
    world.db.flush()
    assert pins_api.has_place_pin_on_member_map(world.db, user_id=a, place_id=place_id) is False

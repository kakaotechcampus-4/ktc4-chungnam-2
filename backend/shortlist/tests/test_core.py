"""순수 함수 테스트 — DB 없이 돌아간다(docs/code-quality.md)."""

from dataclasses import dataclass

from authz.core import Principal
from authz.schemas import Permissions
from shortlist import core
from shortlist.schemas import Route, RouteLeg, ShortlistItem


@dataclass
class _FakeRow:
    id: str
    map_id: str
    added_by: str
    visit_order: int | None = None


def _pin(map_id="map_1", pin_id="pin_1"):
    return {
        "id": pin_id, "map_id": map_id, "category": "음식점", "kind": "확정",
        "visibility": "public", "lat": 35.1, "lng": 129.0, "created_by": "user_1",
        "reaction_summary": {"like": 0, "neutral": 0, "against": 0},
        "permissions": {},
    }


def _principal(role="member"):
    return Principal(user_id="user_1", map_id="map_1", role=role)


def test_to_shortlist_item_response_carries_row_fields_and_pin():
    from pins.schemas import Pin

    row = _FakeRow(id="item_1", map_id="map_1", added_by="user_1", visit_order=3)
    pin = Pin(**_pin())

    item = core.to_shortlist_item_response(row, pin, _principal())

    assert item.id == "item_1"
    assert item.pin is pin
    assert item.visit_order == 3
    assert item.added_by == "user_1"


def test_to_shortlist_item_response_permissions_reflect_member_role():
    from pins.schemas import Pin

    row = _FakeRow(id="item_1", map_id="map_1", added_by="user_1")
    pin = Pin(**_pin())

    item = core.to_shortlist_item_response(row, pin, _principal(role="member"))
    assert item.permissions.can_remove_from_shortlist is True
    assert item.permissions.can_add_to_shortlist is False  # 이미 리스트에 있는 항목이라 항상 False

    item_non_member = core.to_shortlist_item_response(row, pin, _principal(role=None))
    # can()은 role=None이면 항상 False(authz/core.py) — 비구성원 표시는 실제로는 404로 먼저
    # 끝나 이 값을 FE가 보진 않지만, 함수 자체의 순수성은 이렇게 확인한다.
    assert item_non_member.permissions.can_remove_from_shortlist is False


def test_shortlist_changed_event_uses_pin_map_id_and_public_channel():
    item = ShortlistItem(
        id="item_1", pin=_pin(map_id="map_9"), visit_order=None, added_by="user_1",
        permissions=Permissions(),
    )
    event = core.shortlist_changed_event(item, "added")

    assert event.map_id == "map_9"
    assert event.channel == "public"
    assert event.type == "shortlist.changed"
    assert event.payload["action"] == "added"
    assert event.payload["item"]["id"] == "item_1"


@dataclass
class _FakeRouteRow:
    region_label: str
    ordered_pin_ids: list
    total_distance_m: float
    legs: list


def test_to_route_response_rebuilds_legs_from_jsonb():
    row = _FakeRouteRow(
        region_label="구역 1", ordered_pin_ids=["pin_1", "pin_2"], total_distance_m=150.0,
        legs=[{"from_pin_id": "pin_1", "to_pin_id": "pin_2", "distance_m": 150.0, "approx_minutes": 2}],
    )

    route = core.to_route_response(row)

    assert route.region_label == "구역 1"
    assert route.ordered_pin_ids == ["pin_1", "pin_2"]
    assert route.total_distance_m == 150.0
    assert route.legs == [RouteLeg(from_pin_id="pin_1", to_pin_id="pin_2", distance_m=150.0, approx_minutes=2)]


def test_route_recalculated_event_payload_is_a_bare_list_not_wrapped():
    """docs/events.md route.recalculated — data는 다른 이벤트처럼 객체로 감싸지 않고 Route[] 그대로다."""
    routes = [Route(region_label="구역 1", ordered_pin_ids=["pin_1"], total_distance_m=0, legs=[])]
    event = core.route_recalculated_event("map_9", routes)

    assert event.map_id == "map_9"
    assert event.channel == "public"
    assert event.type == "route.recalculated"
    assert isinstance(event.payload, list)
    assert event.payload == [{"region_label": "구역 1", "ordered_pin_ids": ["pin_1"], "total_distance_m": 0, "legs": []}]

"""
pins/core.py 순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md).
"통과하도록" 쓰지 않고 실제로 실패해야 하는 입력을 넣어 확인한다.
"""

import pytest

from pins import core
from pins.errors import PinError
from pins.schemas import Permissions, Pin, PinCreateRequest, ReactionSummary


def _req(**kwargs) -> PinCreateRequest:
    base = {"category": "음식점"}
    base.update(kwargs)
    return PinCreateRequest(**base)


def _pin(visibility: str = "public") -> Pin:
    return Pin(
        id="pin_1",
        map_id="map_1",
        category="음식점",
        kind="일반",
        visibility=visibility,
        lat=35.15,
        lng=129.12,
        created_by="user_1",
        reaction_summary=ReactionSummary(),
        permissions=Permissions(
            can_react=True, can_revert=True, can_add_to_shortlist=True,
            can_remove_from_shortlist=False, can_delete=True,
        ),
    )


# --- resolve_source / validate_create ---------------------------------------

def test_resolve_source_infers_link():
    assert core.resolve_source(_req(link_url="https://map.google.com/x")) == "link"


def test_resolve_source_infers_search():
    assert core.resolve_source(_req(place_id="p1")) == "search"


def test_resolve_source_infers_coordinate():
    assert core.resolve_source(_req(lat=35.1, lng=129.0)) == "coordinate"


def test_resolve_source_explicit_wins():
    assert core.resolve_source(_req(source="search", place_id="p1")) == "search"


def test_resolve_source_missing_raises_validation_error():
    with pytest.raises(PinError) as exc_info:
        core.resolve_source(_req())
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.status_code == 422


def test_resolve_source_ambiguous_input_raises():
    # link_url과 place_id가 동시에 왔는데 source가 없다 — 결정 불가.
    with pytest.raises(PinError) as exc_info:
        core.resolve_source(_req(link_url="https://x", place_id="p1"))
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_validate_create_link_without_link_url_raises():
    with pytest.raises(PinError):
        core.validate_create(_req(source="link"))


def test_validate_create_search_without_place_id_raises():
    with pytest.raises(PinError):
        core.validate_create(_req(source="search"))


def test_validate_create_coordinate_missing_lng_raises():
    with pytest.raises(PinError):
        core.validate_create(_req(source="coordinate", lat=35.1))


@pytest.mark.parametrize("lat,lng", [(91, 129), (-91, 129), (35, 181), (35, -181)])
def test_validate_create_coordinate_out_of_range_raises(lat, lng):
    with pytest.raises(PinError):
        core.validate_create(_req(source="coordinate", lat=lat, lng=lng))


def test_validate_create_valid_coordinate_passes():
    assert core.validate_create(_req(source="coordinate", lat=35.1, lng=129.0)) == "coordinate"


# --- is_duplicate -------------------------------------------------------------

def test_is_duplicate_none_place_id_is_never_duplicate():
    assert core.is_duplicate({"p1", "p2"}, None) is False


def test_is_duplicate_matching_place_id_is_duplicate():
    assert core.is_duplicate({"p1"}, "p1") is True


def test_is_duplicate_non_matching_place_id_is_not_duplicate():
    assert core.is_duplicate({"p1"}, "p2") is False


# --- is_visible_to (가드레일 1) -----------------------------------------------

def test_is_visible_to_public_visible_to_stranger():
    assert core.is_visible_to("public", "owner", "stranger") is True


def test_is_visible_to_private_visible_to_owner():
    assert core.is_visible_to("private", "owner", "owner") is True


def test_is_visible_to_private_hidden_from_stranger():
    assert core.is_visible_to("private", "owner", "stranger") is False


# --- pin_permissions -----------------------------------------------------------

def test_pin_permissions_non_member_everything_false():
    perms = core.pin_permissions("일반", is_member=False)
    assert perms.can_react is False
    assert perms.can_revert is False
    assert perms.can_delete is False
    assert perms.can_add_to_shortlist is False
    assert perms.can_remove_from_shortlist is False


def test_pin_permissions_member_normal_kind_can_add_not_remove():
    perms = core.pin_permissions("일반", is_member=True)
    assert perms.can_add_to_shortlist is True
    assert perms.can_remove_from_shortlist is False
    assert perms.can_delete is True


def test_pin_permissions_member_confirmed_kind_can_remove_not_add():
    perms = core.pin_permissions("확정", is_member=True)
    assert perms.can_add_to_shortlist is False
    assert perms.can_remove_from_shortlist is True


# --- 이벤트 조립 (가드레일 1: private는 전체 채널로 나가지 않는다) --------------------

def test_pin_created_event_public_pin_emits_to_public_channel():
    event = core.pin_created_event(_pin(visibility="public"))
    assert event is not None
    channel, event_type, payload = event
    assert channel == "public"
    assert event_type == "pin.created"
    assert payload["id"] == "pin_1"


def test_pin_created_event_private_pin_emits_nothing():
    assert core.pin_created_event(_pin(visibility="private")) is None


def test_pin_deleted_event_payload_is_pin_id_only():
    event = core.pin_deleted_event("pin_1", visibility="public")
    assert event is not None
    channel, event_type, payload = event
    assert channel == "public"
    assert event_type == "pin.deleted"
    assert payload == {"pin_id": "pin_1"}


def test_pin_deleted_event_private_pin_emits_nothing():
    assert core.pin_deleted_event("pin_1", visibility="private") is None


# --- validate_reaction (가드레일 3) --------------------------------------------

def test_validate_reaction_against_with_text_passes():
    core.validate_reaction("against", "매워요", None)


def test_validate_reaction_against_with_chip_ids_passes():
    core.validate_reaction("against", None, ["spicy_focused"])


def test_validate_reaction_against_whitespace_only_text_raises():
    with pytest.raises(PinError) as exc_info:
        core.validate_reaction("against", "   ", None)
    assert exc_info.value.code == "EVIDENCE_REQUIRED"
    assert exc_info.value.status_code == 422


def test_validate_reaction_against_without_reason_raises():
    with pytest.raises(PinError) as exc_info:
        core.validate_reaction("against", None, None)
    assert exc_info.value.code == "EVIDENCE_REQUIRED"


def test_validate_reaction_against_with_empty_chip_list_raises():
    with pytest.raises(PinError):
        core.validate_reaction("against", None, [])


@pytest.mark.parametrize("reaction_type", ["like", "neutral"])
def test_validate_reaction_like_neutral_never_require_reason(reaction_type):
    core.validate_reaction(reaction_type, None, None)


# --- reaction_changed_event (가드레일 1) ---------------------------------------

def test_reaction_changed_event_public_pin_emits_envelope():
    summary = ReactionSummary(like=1, neutral=0, against=2)
    event = core.reaction_changed_event("pin_1", "public", summary)
    assert event is not None
    channel, event_type, payload = event
    assert channel == "public"
    assert event_type == "reaction.changed"
    assert payload == {"pin_id": "pin_1", "reaction_summary": {"like": 1, "neutral": 0, "against": 2}}


def test_reaction_changed_event_private_pin_emits_nothing():
    event = core.reaction_changed_event("pin_1", "private", ReactionSummary())
    assert event is None

"""
pins/core.py 순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md).
"통과하도록" 쓰지 않고 실제로 실패해야 하는 입력을 넣어 확인한다.

pin_permissions(kind, is_member) 테스트는 여기 없다 — 그 함수 자체가 삭제됐다(#56 이관).
동등성 검증은 pins/tests/test_permissions_contract.py + authz/tests/test_permissions.py가 맡는다.
"""

import pytest
from pydantic import ValidationError

from authz.core import Principal
from common.errors import AppError
from pins import core
from pins.schemas import Pin, PinCreateSearch, ReactionSummary


def _req(**kwargs) -> PinCreateSearch:
    base = {"category": "음식점", "place_id": "kakao:1", "place_name": "성수 칼국수", "lat": 37.54, "lng": 127.05}
    base.update(kwargs)
    return PinCreateSearch(**base)


def _principal(role: str | None = "member") -> Principal:
    return Principal(user_id="user_1", map_id="map_1", role=role)


def _pin(visibility: str = "public") -> Pin:
    record = core.PinRecord(
        id="pin_1", map_id="map_1", category="음식점", kind="일반", visibility=visibility,
        lat=35.15, lng=129.12, created_by="user_1", reaction_counts=core.ReactionCounts(),
    )
    return core.to_pin_response(record, _principal())


# --- validate_create / 카카오 URL ---------------------------------------------

def test_validate_create_accepts_search_hint():
    core.validate_create(_req())
    core.validate_create(_req(source="search"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"link_url": "https://map.google.com/x"},
        {"source": "link"},
        {"source": "link", "link_url": "https://map.google.com/x"},
    ],
)
def test_validate_create_rejects_link_paths(kwargs):
    """#148 — v1은 링크 핀을 거절한다. 프론트가 그대로 보여줄 문장이 메시지다."""
    with pytest.raises(AppError) as exc_info:
        core.validate_create(_req(**kwargs))
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.status == 422
    assert exc_info.value.message == core.LINK_PIN_REJECTED_MESSAGE


def test_validate_create_rejects_coordinate_source():
    """#195 — 좌표로 핀을 찍는 경로는 없다(자체 DB 장소만)."""
    with pytest.raises(AppError) as exc_info:
        core.validate_create(_req(source="coordinate"))
    assert exc_info.value.code == "VALIDATION_ERROR" and exc_info.value.status == 422
    assert exc_info.value.message == core.COORDINATE_PIN_REJECTED_MESSAGE


def test_create_request_requires_all_hint_fields():
    for missing in ("place_id", "place_name", "lat", "lng"):
        base = {"category": "음식점", "place_id": "kakao:1", "place_name": "x", "lat": 37.5, "lng": 127.0}
        del base[missing]
        with pytest.raises(ValidationError):
            PinCreateSearch(**base)


@pytest.mark.parametrize("lat,lng", [(91, 127), (-91, 127), (37, 181), (37, -181)])
def test_create_request_rejects_out_of_range_coordinates(lat, lng):
    with pytest.raises(ValidationError):
        _req(lat=lat, lng=lng)


def test_validate_category_matches():
    core.validate_category_matches("카페", "카페")
    with pytest.raises(AppError) as exc_info:
        core.validate_category_matches("카페", "음식점")
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_kakao_place_url_only_for_kakao_ids():
    assert core.kakao_place_url("kakao:1234") == "https://place.map.kakao.com/1234"
    assert core.kakao_place_url("naver:1234") is None
    assert core.kakao_place_url("kakao:") is None
    assert core.kakao_place_url("1234") is None
    assert core.kakao_place_url("kakao:../../evil?x=1#frag") is None   # #248 — 숫자가 아니면 링크로 못 만든다
    assert core.kakao_place_url("kakao:12a4") is None
    assert core.kakao_place_url("kakao:" + "9" * 21) is None


# --- is_duplicate -------------------------------------------------------------

def test_is_duplicate_none_place_id_is_never_duplicate():
    assert core.is_duplicate({"p1", "p2"}, None) is False


def test_is_duplicate_matching_place_id_is_duplicate():
    assert core.is_duplicate({"p1"}, "p1") is True


def test_is_duplicate_non_matching_place_id_is_not_duplicate():
    assert core.is_duplicate({"p1"}, "p2") is False


# --- kind_after_unconfirm -------------------------------------------------------

def test_kind_after_unconfirm_ai_origin_returns_ai_recommended():
    assert core.kind_after_unconfirm("ai") == "AI추천"


def test_kind_after_unconfirm_direct_origin_returns_normal():
    assert core.kind_after_unconfirm("direct") == "일반"


# --- to_pin_response — authz.core.permissions_for 위임 확인 ------------------------

def test_to_pin_response_member_gets_permissions_from_authz():
    record = core.PinRecord(
        id="pin_1", map_id="map_1", category="음식점", kind="일반", visibility="public",
        lat=35.1, lng=129.0, created_by="user_1", reaction_counts=core.ReactionCounts(),
    )
    pin = core.to_pin_response(record, _principal(role="member"))
    assert pin.permissions.can_react is True
    assert pin.permissions.can_add_to_shortlist is True
    assert pin.permissions.can_remove_from_shortlist is False


def test_to_pin_response_non_member_gets_all_false():
    record = core.PinRecord(
        id="pin_1", map_id="map_1", category="음식점", kind="일반", visibility="public",
        lat=35.1, lng=129.0, created_by="user_1", reaction_counts=core.ReactionCounts(),
    )
    pin = core.to_pin_response(record, _principal(role=None))
    assert pin.permissions.can_react is False
    assert pin.permissions.can_delete is False


# --- 이벤트 조립 --------------------

def test_pin_created_event_public_pin_emits_to_public_channel():
    event = core.pin_created_event(_pin(visibility="public"))
    assert event is not None
    assert event.map_id == "map_1"
    assert event.channel == "public"
    assert event.type == "pin.created"
    assert event.payload["id"] == "pin_1"
    assert event.recipient_user_id is None


def test_pin_deleted_event_payload_is_pin_id_only():
    event = core.pin_deleted_event("pin_1", "map_1")
    assert event is not None
    assert event.map_id == "map_1"
    assert event.channel == "public"
    assert event.type == "pin.deleted"
    assert event.payload == {"pin_id": "pin_1"}


# --- validate_reaction (가드레일 3) --------------------------------------------

def test_validate_reaction_against_with_text_passes():
    core.validate_reaction("against", "매워요", None)


def test_validate_reaction_against_with_chip_ids_passes():
    core.validate_reaction("against", None, ["spicy_focused"])


def test_validate_reaction_against_whitespace_only_text_raises():
    with pytest.raises(AppError) as exc_info:
        core.validate_reaction("against", "   ", None)
    assert exc_info.value.code == "EVIDENCE_REQUIRED"
    assert exc_info.value.status == 422


def test_validate_reaction_against_without_reason_raises():
    with pytest.raises(AppError) as exc_info:
        core.validate_reaction("against", None, None)
    assert exc_info.value.code == "EVIDENCE_REQUIRED"


def test_validate_reaction_against_with_empty_chip_list_raises():
    with pytest.raises(AppError):
        core.validate_reaction("against", None, [])


@pytest.mark.parametrize("text", ["​", " ​‍﻿ "])
def test_validate_reaction_against_zero_width_only_text_raises(text):
    with pytest.raises(AppError) as exc_info:
        core.validate_reaction("against", text, None)
    assert exc_info.value.code == "EVIDENCE_REQUIRED"


@pytest.mark.parametrize("chips", [[""], ["  "], ["​"], ["ok", ""]])
@pytest.mark.parametrize("reaction_type", ["against", "like"])
def test_validate_reaction_blank_chip_is_a_validation_error(reaction_type, chips):
    with pytest.raises(AppError) as exc_info:
        core.validate_reaction(reaction_type, "매워요", chips)
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.status == 422


def test_reason_content_strips_and_rejects_invisible_only():
    assert core.reason_content(" 매워요 ") == "매워요"
    assert core.reason_content(None) is None
    assert core.reason_content("​") is None


def test_validate_reaction_like_never_requires_reason():
    core.validate_reaction("like", None, None)


# --- reaction_changed_event (가드레일 1) ---------------------------------------

def test_reaction_changed_event_public_pin_emits_envelope():
    summary = ReactionSummary(like=1, against=2)
    event = core.reaction_changed_event("pin_1", "map_1", summary, "user_2", "민수", "against")
    assert event is not None
    assert event.map_id == "map_1"
    assert event.channel == "public"
    assert event.type == "reaction.changed"
    assert event.payload == {
        "pin_id": "pin_1", "reaction_summary": {"like": 1, "against": 2},
        "user_id": "user_2", "display_name": "민수", "type": "against",
    }


def test_reaction_changed_event_delete_has_null_type_and_never_carries_reasons():
    event = core.reaction_changed_event("pin_1", "map_1", ReactionSummary(), "user_2", "민수", None)
    assert event.payload["type"] is None
    assert not {"reason_text", "reason_chip_ids", "my_reaction"} & set(event.payload)


# --- #369 핀 작성자 표시 ---

def test_author_display_name_withdrawn_wins_over_membership():
    """탈퇴자는 멤버십 행이 남아 현재 구성원으로 잡힌다(#245) — 그래도 '탈퇴한 구성원'이 먼저다."""
    assert core.author_display_name("철수", is_withdrawn=True, is_current_member=True) == "탈퇴한 구성원"
    assert core.author_display_name("철수", is_withdrawn=True, is_current_member=False) == "탈퇴한 구성원"


def test_author_display_name_left_member():
    assert core.author_display_name("철수", is_withdrawn=False, is_current_member=False) == "나간 구성원"


def test_author_display_name_current_member_keeps_real_name():
    assert core.author_display_name("철수", is_withdrawn=False, is_current_member=True) == "철수"
    assert core.author_display_name(None, is_withdrawn=False, is_current_member=True) is None


def test_withdrawn_author_name_matches_auth():
    from auth.api import WITHDRAWN_DISPLAY_NAME

    assert core.WITHDRAWN_AUTHOR_NAME == WITHDRAWN_DISPLAY_NAME

"""
core.permissions_for()의 리소스별 필드 채움 규칙 + backend/pins/core.py::pin_permissions와의
동등성(#56 이관 안전망). pins를 import하지 않는다 — 기대값은 표로 하드코딩한다(의존 방향 유지:
authz는 pins보다 아래층이라 pins를 몰라야 한다).
"""

import pytest

from authz.core import Principal, Resource, permissions_for

MAP = "map_1"


def _principal(role, user_id="user_1") -> Principal:
    return Principal(user_id=user_id, map_id=MAP, role=role)


def _resource(type_, author_id=None, kind=None) -> Resource:
    return Resource(type=type_, map_id=MAP, author_id=author_id, kind=kind)


# --- pin ---


def test_pin_member_general_kind():
    user = _principal(role="member")
    perms = permissions_for(user, _resource("pin", kind="일반"))
    dumped = perms.model_dump(exclude_none=True)
    assert dumped == {
        "can_react": True,
        "can_revert": True,
        "can_delete": True,
        "can_add_to_shortlist": True,
        "can_remove_from_shortlist": False,
    }


def test_pin_member_confirmed_kind_gates_shortlist_direction():
    user = _principal(role="member")
    perms = permissions_for(user, _resource("pin", kind="확정"))
    assert perms.can_add_to_shortlist is False
    assert perms.can_remove_from_shortlist is True


def test_pin_non_member_all_false_not_none():
    user = _principal(role=None)
    perms = permissions_for(user, _resource("pin", kind="일반"))
    dumped = perms.model_dump(exclude_none=True)
    assert dumped == {
        "can_react": False,
        "can_revert": False,
        "can_delete": False,
        "can_add_to_shortlist": False,
        "can_remove_from_shortlist": False,
    }


# --- evidence_line ---


def test_evidence_line_only_fills_can_disable():
    author = _principal(role="member", user_id="user_1")
    perms = permissions_for(author, _resource("evidence_line", author_id="user_1"))
    assert perms.model_dump(exclude_none=True) == {"can_disable": True}


def test_evidence_line_non_author_can_disable_false():
    other = _principal(role="member", user_id="user_2")
    perms = permissions_for(other, _resource("evidence_line", author_id="user_1"))
    assert perms.model_dump(exclude_none=True) == {"can_disable": False}


# --- shortlist_item ---


def test_shortlist_item_add_always_false_remove_follows_can():
    member = _principal(role="member")
    perms = permissions_for(member, _resource("shortlist_item"))
    assert perms.can_add_to_shortlist is False
    assert perms.can_remove_from_shortlist is True

    non_member = _principal(role=None)
    perms_nm = permissions_for(non_member, _resource("shortlist_item"))
    assert perms_nm.can_add_to_shortlist is False
    assert perms_nm.can_remove_from_shortlist is False


# --- 지원하지 않는 리소스 종류 ---


def test_unsupported_resource_type_raises():
    user = _principal(role="member")
    with pytest.raises(ValueError):
        permissions_for(user, _resource("candidate", author_id="user_1"))
    with pytest.raises(ValueError):
        permissions_for(user, _resource("map"))


# --- backend/pins/core.py::pin_permissions 동등성 (#56 이관 안전망) ---
#
# pins/core.py 현재 구현(수정하지 않음, 여기 표로만 옮겨 대조):
#
#   def pin_permissions(kind: str, is_member: bool) -> Permissions:
#       return Permissions(
#           can_react=is_member,
#           can_revert=is_member,
#           can_delete=is_member,
#           can_add_to_shortlist=is_member and kind != "확정",
#           can_remove_from_shortlist=is_member and kind == "확정",
#       )
#
# pins의 Permissions는 5개 필드가 필수라 항상 나온다(can_disable만 optional). 그래서 비교는
# "실제로 나가는 JSON이 같은가"를 봐야 하므로 Python 객체가 아니라 model_dump(exclude_none=True)
# dict로 비교한다 — authz 쪽은 6개 필드가 전부 optional이라 값이 없으면 아예 빠지는데, pin 응답에서는
# 5개 필드를 항상 채우므로(permissions_for의 _pin_permissions) 결과 dict가 같아야 맞다.

PIN_KINDS = ["일반", "AI추천", "확정"]


@pytest.mark.parametrize("kind", PIN_KINDS)
@pytest.mark.parametrize("is_member", [True, False])
def test_pin_permissions_matches_pins_module(kind, is_member):
    user = _principal(role="member" if is_member else None)
    resource = _resource("pin", kind=kind)
    dumped = permissions_for(user, resource).model_dump(exclude_none=True)

    expected = {
        "can_react": is_member,
        "can_revert": is_member,
        "can_delete": is_member,
        "can_add_to_shortlist": is_member and kind != "확정",
        "can_remove_from_shortlist": is_member and kind == "확정",
    }
    assert dumped == expected

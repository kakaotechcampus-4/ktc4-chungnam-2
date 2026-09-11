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


# backend/pins/core.py::pin_permissions와의 동등성 검증은 pins/tests/test_permissions_contract.py로
# 이관됐다(#56, pins/mentor-review-plan.md) — pin_permissions 자체가 삭제됐고, pins가 authz를
# import하는 방향이 허용되므로 그 안전망은 이제 pins 쪽에 둔다.

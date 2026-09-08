"""
core.can()의 역할별·범위별 판정 — 순수 함수라 모의 객체 없이 직접 호출한다.
"""

import pytest

from authz.core import Principal, Resource, can

MAP = "map_1"
OTHER_MAP = "map_2"


def _principal(role, user_id="user_1", map_id=MAP) -> Principal:
    return Principal(user_id=user_id, map_id=map_id, role=role)


def _resource(type_, map_id=MAP, author_id=None, kind=None) -> Resource:
    return Resource(type=type_, map_id=map_id, author_id=author_id, kind=kind)


# --- 비구성원 ---


def test_non_member_everything_false():
    user = _principal(role=None)
    assert can(user, "pin.react", _resource("pin")) is False
    assert can(user, "pin.delete", _resource("pin")) is False
    assert can(user, "shortlist.add", _resource("pin")) is False
    assert can(user, "evidence.disable", _resource("evidence_line")) is False


def test_non_member_who_is_author_still_denied():
    """author는 member 위에 얹히는 추가 범위지 독립 역할이 아니다(permissions.md 25·41행).
    비구성원이 우연히 author_id와 일치한다고 evidence.disable·candidate.view_private가
    열리면 그건 권한 상승이다."""
    user = _principal(role=None, user_id="user_9")
    evidence = _resource("evidence_line", author_id="user_9")
    candidate = _resource("candidate", author_id="user_9")
    assert can(user, "evidence.disable", evidence) is False
    assert can(user, "candidate.view_private", candidate) is False


# --- 교차 지도 차단 ---


@pytest.mark.parametrize("role", ["member", "owner"])
def test_cross_map_raises_value_error(role):
    user = _principal(role=role, map_id=MAP)
    resource = _resource("pin", map_id=OTHER_MAP)
    with pytest.raises(ValueError):
        can(user, "pin.react", resource)


def test_cross_map_raises_even_for_author_scope():
    user = _principal(role="member", user_id="user_1", map_id=MAP)
    resource = _resource("evidence_line", map_id=OTHER_MAP, author_id="user_1")
    with pytest.raises(ValueError):
        can(user, "evidence.disable", resource)


# --- 액션-리소스 종류 혼동 차단 ---


def test_action_resource_type_mismatch_returns_false_not_true():
    user = _principal(role="member", user_id="user_1")
    # candidate 전용 액션을 pin에 물으면 False여야 한다 — author_id가 일치해도 마찬가지.
    pin = _resource("pin", author_id="user_1")
    assert can(user, "recommend.publish", pin) is False


def test_action_resource_type_mismatch_pin_action_on_evidence_line():
    user = _principal(role="member")
    assert can(user, "pin.delete", _resource("evidence_line")) is False


def test_unknown_action_returns_false():
    user = _principal(role="owner")
    assert can(user, "totally.unknown.action", _resource("pin")) is False


# --- member 액션 ---


def test_member_pin_delete_regardless_of_authorship():
    """9/4 결정 #25 — 핀 삭제는 구성원 누구나. 작성자가 아니어도 True."""
    user = _principal(role="member", user_id="user_1")
    pin = _resource("pin", author_id="someone_else")
    assert can(user, "pin.delete", pin) is True


def test_member_pin_revert():
    user = _principal(role="member")
    assert can(user, "pin.revert", _resource("pin")) is True


def test_non_member_pin_revert_false():
    user = _principal(role=None)
    assert can(user, "pin.revert", _resource("pin")) is False


def test_member_shortlist_add_and_remove():
    user = _principal(role="member")
    assert can(user, "shortlist.add", _resource("pin")) is True
    assert can(user, "shortlist.remove", _resource("pin")) is True
    assert can(user, "shortlist.remove", _resource("shortlist_item")) is True


def test_shortlist_add_not_valid_for_shortlist_item():
    """shortlist.add의 대상은 pin뿐이다 — shortlist_item에 물으면 False."""
    user = _principal(role="member")
    assert can(user, "shortlist.add", _resource("shortlist_item")) is False


# --- owner ---


def test_owner_inherits_member_actions():
    user = _principal(role="owner")
    assert can(user, "pin.delete", _resource("pin")) is True
    assert can(user, "shortlist.add", _resource("pin")) is True


def test_owner_only_actions():
    owner = _principal(role="owner")
    member = _principal(role="member")
    map_resource = _resource("map")
    assert can(owner, "map.settings.edit", map_resource) is True
    assert can(owner, "member.kick", map_resource) is True
    assert can(member, "map.settings.edit", map_resource) is False
    assert can(member, "member.kick", map_resource) is False


# --- author 범위 ---


def test_author_scope_does_not_leak_to_pin():
    """자기가 만든 핀이라고 evidence.disable이 열리면 안 된다 — author scope는
    evidence_line·candidate뿐이다."""
    user = _principal(role="member", user_id="user_1")
    pin = _resource("pin", author_id="user_1")
    assert can(user, "evidence.disable", pin) is False


def test_evidence_disable_author_only():
    author = _principal(role="member", user_id="user_1")
    other_member = _principal(role="member", user_id="user_2")
    evidence = _resource("evidence_line", author_id="user_1")
    assert can(author, "evidence.disable", evidence) is True
    assert can(other_member, "evidence.disable", evidence) is False


def test_recommend_publish_requires_being_the_requester():
    requester = _principal(role="member", user_id="user_1")
    other_member = _principal(role="member", user_id="user_2")
    candidate = _resource("candidate", author_id="user_1")
    assert can(requester, "recommend.publish", candidate) is True
    assert can(other_member, "recommend.publish", candidate) is False


def test_candidate_view_private_author_only_even_for_owner():
    """owner.actions에 candidate.view_private가 없다 — 지도 생성자라고 남의 비공개 후보를
    보면 가드레일 1(비공개 후보 유출 금지) 위반이다."""
    owner = _principal(role="owner", user_id="owner_1")
    requester = _principal(role="member", user_id="user_1")
    candidate = _resource("candidate", author_id="user_1")
    assert can(requester, "candidate.view_private", candidate) is True
    assert can(owner, "candidate.view_private", candidate) is False

"""
docs/permissions.md "15-1 표와의 매핑" 절의 5개 행 전부를 검증한다.

주의: backend/authz/CLAUDE.md의 완료 정의는 "4개 행"이라고 적혀 있지만 실제 docs/permissions.md의
표는 5행이다(반경 조정 행이 별도로 있다) — for_Root.md에 문서 불일치로 보고했고, 여기서는 5행
전부를 덮는다.
"""

from authz.core import Principal, Resource, can
from authz.policy import ACTION_RESOURCE_TYPES, POLICY

MAP = "map_1"


def _principal(role, user_id="user_1") -> Principal:
    return Principal(user_id=user_id, map_id=MAP, role=role)


def _resource(type_, author_id=None, kind=None) -> Resource:
    return Resource(type=type_, map_id=MAP, author_id=author_id, kind=kind)


# 1. 확정 리스트 추가·제외 — 구성원 누구나


def test_row1_shortlist_add_remove_member_anyone():
    member = _principal(role="member")
    non_member = _principal(role=None)
    pin = _resource("pin")
    assert can(member, "shortlist.add", pin) is True
    assert can(member, "shortlist.remove", pin) is True
    assert can(non_member, "shortlist.add", pin) is False
    assert can(non_member, "shortlist.remove", pin) is False


# 2. 핀 삭제 — 구성원 누구나 (9/4 결정 #25)


def test_row2_pin_delete_member_anyone_not_just_author():
    member = _principal(role="member", user_id="user_1")
    pin = _resource("pin", author_id="someone_else")
    assert can(member, "pin.delete", pin) is True


# 3. 근거 리스트에서 항목 빼기 — 자기가 쓴 것만


def test_row3_evidence_disable_author_only():
    author = _principal(role="member", user_id="user_1")
    other = _principal(role="member", user_id="user_2")
    evidence = _resource("evidence_line", author_id="user_1")
    assert can(author, "evidence.disable", evidence) is True
    assert can(other, "evidence.disable", evidence) is False


# 4. 핀 되돌리기 — 구성원 누구나


def test_row4_pin_revert_member_anyone():
    member = _principal(role="member")
    non_member = _principal(role=None)
    pin = _resource("pin")
    assert can(member, "pin.revert", pin) is True
    assert can(non_member, "pin.revert", pin) is False


# 5. 반경 조정 — 별도 권한 불필요 (반경 사유도 evidence_line이므로 3행 규칙을 그대로 상속)


def test_row5_no_dedicated_radius_action_exists():
    assert not any(action.startswith("radius.") for spec in POLICY.values() for action in spec.actions)
    assert not any(action.startswith("radius.") for action in ACTION_RESOURCE_TYPES)


def test_row5_radius_reason_inherits_evidence_line_rule():
    """반경 조정 사유도 evidence_line이라 3행과 같은 판정 함수를 그대로 탄다 — 별도 액션이
    없다는 게 핵심이므로, evidence.disable 판정이 반경 사유가 담긴 evidence_line에도 동일하게
    적용됨을 확인한다."""
    author = _principal(role="member", user_id="user_1")
    other = _principal(role="member", user_id="user_2")
    radius_evidence = _resource("evidence_line", author_id="user_1")
    assert can(author, "evidence.disable", radius_evidence) is True
    assert can(other, "evidence.disable", radius_evidence) is False

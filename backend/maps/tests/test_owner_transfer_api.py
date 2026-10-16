"""
POST /maps/{mapId}/owner(#468) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
"""

import pytest

from common.errors import AppError
from maps.core import MembershipEntry, check_owner_target
from maps.tests.test_delete_leave_api import _auth, _create_map, _events, _join, _roles, _withdraw

from datetime import datetime, timezone
import uuid


def _transfer(app_client, map_id, to_user_id, user_id="user_1"):
    return app_client.post(f"/maps/{map_id}/owner", json={"user_id": to_user_id}, cookies=_auth(user_id))


def test_owner_hands_over_and_stays_as_member(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2", "user_3")

    resp = _transfer(app_client, map_id, "user_2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 응답은 요청자(이제 구성원) 기준 Map이다
    assert body["id"] == map_id
    assert body["my_role"] == "member"
    assert body["permissions"]["can_delete"] is False and body["permissions"]["can_leave"] is True
    assert "next_owner" not in body
    assert body["member_count"] == 3

    assert _roles(db_session, map_id) == {"user_1": "member", "user_2": "owner", "user_3": "member"}
    members = {m["user_id"]: m["role"] for m in app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_3")).json()}
    assert members == {"user_1": "member", "user_2": "owner", "user_3": "member"}
    # 새 방장 기준 상세
    detail = app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()
    assert detail["my_role"] == "owner" and detail["permissions"]["can_delete"] is True


def test_owner_changed_event_is_recorded_and_member_left_is_not(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _transfer(app_client, map_id, "user_2")

    (event,) = _events(db_session, map_id, "owner.changed")
    assert event.channel == "public"
    assert event.payload == {"map_id": map_id, "from_user_id": "user_1", "to_user_id": "user_2"}
    assert _events(db_session, map_id, "member.left") == []


def test_former_owner_is_a_plain_member_afterwards(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _transfer(app_client, map_id, "user_2")
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 403
    assert _transfer(app_client, map_id, "user_1").status_code == 403  # 더는 방장이 아니라서 다시 넘길 수 없다
    # 새 방장은 다시 넘길 수 있다
    assert _transfer(app_client, map_id, "user_1", "user_2").status_code == 200


def test_former_owner_can_leave_after_handing_over(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _transfer(app_client, map_id, "user_2")
    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204
    assert _roles(db_session, map_id) == {"user_2": "owner"}
    # 이미 방장이 아니었으므로 위임이 없다 — new_owner_user_id는 null
    (left,) = _events(db_session, map_id, "member.left")
    assert left.payload["new_owner_user_id"] is None


@pytest.mark.parametrize("target", ["user_1", "outsider", "no-such-user", ""])
def test_invalid_targets_are_422_owner_target_invalid(app_client, db_session, target):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    resp = _transfer(app_client, map_id, target)
    assert (resp.status_code, resp.json()["code"]) == (422, "OWNER_TARGET_INVALID")
    assert _roles(db_session, map_id) == {"user_1": "owner", "user_2": "member"}
    assert _events(db_session, map_id, "owner.changed") == []


def test_withdrawn_member_is_not_a_valid_target(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _withdraw(db_session, "user_2")
    resp = _transfer(app_client, map_id, "user_2")
    assert (resp.status_code, resp.json()["code"]) == (422, "OWNER_TARGET_INVALID")
    assert _roles(db_session, map_id)["user_1"] == "owner"


def test_member_who_left_is_not_a_valid_target(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2", "user_3")
    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_3")).status_code == 204
    assert _transfer(app_client, map_id, "user_3").status_code == 422


def test_missing_user_id_is_422_validation_error(app_client):
    map_id = _create_map(app_client)
    resp = app_client.post(f"/maps/{map_id}/owner", json={}, cookies=_auth("user_1"))
    assert (resp.status_code, resp.json()["code"]) == (422, "VALIDATION_ERROR")


def test_member_gets_403_outsider_404_anonymous_401(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2", "user_3")
    assert _transfer(app_client, map_id, "user_3", "user_2").status_code == 403
    assert _transfer(app_client, map_id, "user_2", "outsider").status_code == 404
    assert app_client.post(f"/maps/{map_id}/owner", json={"user_id": "user_2"}).status_code == 401
    assert _roles(db_session, map_id)["user_1"] == "owner"
    assert _events(db_session, map_id, "owner.changed") == []


def test_deleted_map_is_404(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    assert _transfer(app_client, map_id, "user_2").status_code == 404


def _entry(user_id, role="member"):
    return MembershipEntry(id=uuid.uuid4(), user_id=user_id, role=role, joined_at=datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_check_owner_target_rules():
    roster = [_entry("a", "owner"), _entry("b"), _entry("c")]
    check_owner_target(roster, set(), "a", "b", guests=set())  # 통과
    for target, withdrawn in (("a", set()), ("zzz", set()), ("c", {"c"})):
        with pytest.raises(AppError) as err:
            check_owner_target(roster, withdrawn, "a", target, guests=set())
        assert err.value.code == "OWNER_TARGET_INVALID"

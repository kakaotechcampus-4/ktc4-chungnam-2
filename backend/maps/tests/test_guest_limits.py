"""
게스트 제한(#472) 통합 테스트 — 지도 만들기 403, 방장 후임·직접 넘기기에서 게스트 제외.
게스트 계정은 있는 사용자의 로그인 수단을 지워 만든다(#694, auth.testing.make_guest — 실제 PostgreSQL 필요).
"""

import pytest

import maps.api as maps_api
from auth.testing import make_guest
from maps.core import MAP_LIMIT, MembershipEntry, check_owner_target
from maps.models import Map as MapRow
from maps.tests.test_delete_leave_api import (
    _auth, _create_map, _events, _fill_to_limit, _join, _roles, _set_joined_at,
)
from maps.tests.test_owner_transfer_api import _transfer

GUEST = "user_guest"


def _make_guest(db_session, user_id=GUEST):
    make_guest(db_session, user_id)
    db_session.commit()


def test_guest_cannot_create_a_map(app_client, db_session):
    _make_guest(db_session)
    resp = app_client.post(
        "/maps", json={"title": "게스트 지도", "start_date": "2026-10-20", "end_date": "2026-10-22"},
        cookies=_auth(GUEST),
    )
    assert (resp.status_code, resp.json()["code"]) == (403, "GUEST_NOT_ALLOWED")
    assert app_client.get("/maps", cookies=_auth(GUEST)).json()["items"] == []


def test_guest_check_comes_before_the_map_limit(app_client, db_session):
    _fill_to_limit(app_client, GUEST)   # 게스트가 되기 전에 상한까지 채워 둔다
    _make_guest(db_session)
    resp = app_client.post(
        "/maps", json={"title": "하나 더", "start_date": "2026-10-20", "end_date": "2026-10-22"},
        cookies=_auth(GUEST),
    )
    assert (resp.status_code, resp.json()["code"]) == (403, "GUEST_NOT_ALLOWED")
    assert len(app_client.get("/maps", cookies=_auth(GUEST)).json()["items"]) == MAP_LIMIT


def test_guest_acts_as_a_regular_member_otherwise(app_client, db_session):
    _make_guest(db_session)
    map_id = _create_map(app_client)
    _join(app_client, map_id, GUEST)
    assert app_client.get(f"/maps/{map_id}", cookies=_auth(GUEST)).json()["my_role"] == "member"
    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1")).json()
    assert {m["user_id"] for m in members} == {"user_1", GUEST}
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["member_count"] == 2


def test_handing_over_to_a_guest_is_422(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, GUEST, "user_2")
    _make_guest(db_session)
    resp = _transfer(app_client, map_id, GUEST)
    assert (resp.status_code, resp.json()["code"]) == (422, "OWNER_TARGET_INVALID")
    assert _roles(db_session, map_id)["user_1"] == "owner"
    assert _transfer(app_client, map_id, "user_2").status_code == 200


def test_check_owner_target_rejects_guests():
    from datetime import datetime, timezone
    import uuid
    from common.errors import AppError

    joined = datetime(2026, 10, 1, tzinfo=timezone.utc)
    roster = [MembershipEntry(id=uuid.uuid4(), user_id=u, role=r, joined_at=joined)
              for u, r in (("a", "owner"), ("g", "member"))]
    with pytest.raises(AppError) as err:
        check_owner_target(roster, set(), "a", "g", guests={"g"})
    assert err.value.code == "OWNER_TARGET_INVALID"


def test_owner_leaving_skips_a_guest_who_joined_earlier(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, GUEST, "user_2")
    _make_guest(db_session)
    _set_joined_at(db_session, map_id, [GUEST, "user_2"])   # 게스트가 먼저 들어왔다

    detail = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert detail["next_owner"]["user_id"] == "user_2"
    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204
    assert _roles(db_session, map_id) == {GUEST: "member", "user_2": "owner"}
    [left] = _events(db_session, map_id, "member.left")
    assert left.payload["new_owner_user_id"] == "user_2"


def test_owner_with_only_guests_left_cannot_leave(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, GUEST)
    _make_guest(db_session)

    detail = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert detail["permissions"]["can_leave"] is False and "next_owner" not in detail
    resp = app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1"))
    assert (resp.status_code, resp.json()["code"]) == (409, "OWNER_CANNOT_LEAVE")
    assert _roles(db_session, map_id)["user_1"] == "owner"


def test_withdrawing_owner_skips_guests_or_deletes_the_map(app_client, db_session):
    shared = _create_map(app_client, title="게스트 먼저")
    only_guest = _create_map(app_client, title="게스트뿐")
    _join(app_client, shared, GUEST, "user_2")
    _join(app_client, only_guest, GUEST)
    _make_guest(db_session)
    _set_joined_at(db_session, shared, [GUEST, "user_2"])

    maps_api.transfer_or_delete_owned_maps(db_session, "user_1")
    db_session.commit()

    assert _roles(db_session, shared) == {"user_1": "member", GUEST: "member", "user_2": "owner"}
    assert db_session.get(MapRow, only_guest).deleted_at is not None
    assert len(_events(db_session, only_guest, "map.deleted")) == 1

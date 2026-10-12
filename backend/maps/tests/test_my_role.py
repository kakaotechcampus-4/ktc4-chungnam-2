"""Map.my_role·created_by_me(#391). my_role은 memberships.role(위임되면 바뀐다), created_by_me는
maps.created_by == 요청자(위임돼도 안 바뀐다)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from auth.testing import session_cookie
from maps.models import Membership as MembershipRow

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _auth(user_id):
    return session_cookie(user_id)


def _create_map(app_client, user_id="user_1"):
    resp = app_client.post(
        "/maps",
        json={"title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12"},
        cookies=_auth(user_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _roles(body):
    return body["my_role"], body["created_by_me"]


def test_creator_is_owner_and_created_by_me_on_create_detail_and_list(app_client):
    created = _create_map(app_client)
    assert _roles(created) == ("owner", True)
    assert _roles(app_client.get(f"/maps/{created['id']}", cookies=_auth("user_1")).json()) == ("owner", True)
    [listed] = app_client.get("/maps", cookies=_auth("user_1")).json()
    assert _roles(listed) == ("owner", True)


def test_joined_member_is_member_and_not_creator_on_accept_detail_and_list(app_client):
    map_id = _create_map(app_client)["id"]
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()["token"]

    accepted = app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2"))
    assert _roles(accepted.json()) == ("member", False)
    assert _roles(app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()) == ("member", False)
    [listed] = app_client.get("/maps", cookies=_auth("user_2")).json()
    assert _roles(listed) == ("member", False)


def test_after_handing_over_owner_the_creator_is_member_but_still_created_by_me(app_client, db_session):
    """방장 위임(방장이 나가면 가장 먼저 들어온 구성원에게 넘어간다, #369) 뒤 — 나갔다가 다시
    들어온 만든 사람은 member이지만 만든 사람 기록(created_by_me)은 그대로다."""
    map_id = _create_map(app_client)["id"]
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()["token"]
    app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2"))
    db_session.execute(
        update(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_1")
        .values(joined_at=T0)
    )
    db_session.execute(
        update(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2")
        .values(joined_at=T0 + timedelta(minutes=1))
    )
    db_session.commit()

    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204
    assert app_client.post(f"/invites/{token}/accept", cookies=_auth("user_1")).status_code == 200

    mine = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert _roles(mine) == ("member", True)
    [listed] = app_client.get("/maps", cookies=_auth("user_1")).json()
    assert _roles(listed) == ("member", True)

    new_owner = app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()
    assert _roles(new_owner) == ("owner", False)

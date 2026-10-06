"""
지도 삭제·나가기·방장 위임(#369) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).

joined_at은 server_default now()라 한 테스트(=한 트랜잭션) 안에서는 모두 같은 값이 된다. 들어온 순서를
검증하는 테스트는 _set_joined_at으로 시각을 직접 정한다 — 안 그러면 memberships.id(무작위 UUID)
순서로 갈려 무작위로 통과한다.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from auth.models import User
from auth.testing import session_cookie
from common.events import EventLog
from maps import api as maps_api
from maps.api import DbMembershipGateway
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from recommend.models import EvidenceLine, RecommendRun

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _auth(user_id):
    return session_cookie(user_id)


def _create_map(app_client, user_id="user_1", title="부산 여행"):
    resp = app_client.post(
        "/maps", json={"title": title, "start_date": "2026-10-10", "end_date": "2026-10-12"}, cookies=_auth(user_id)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _invite_token(app_client, map_id, user_id="user_1"):
    resp = app_client.post(f"/maps/{map_id}/invite", cookies=_auth(user_id))
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def _join(app_client, map_id, *user_ids):
    token = _invite_token(app_client, map_id)
    for user_id in user_ids:
        assert app_client.post(f"/invites/{token}/accept", cookies=_auth(user_id)).status_code == 200


def _set_joined_at(db_session, map_id, order):
    """order의 순서대로 1분 간격으로 들어온 것으로 만든다."""
    for i, user_id in enumerate(order):
        db_session.execute(
            update(MembershipRow)
            .where(MembershipRow.map_id == map_id, MembershipRow.user_id == user_id)
            .values(joined_at=T0 + timedelta(minutes=i))
        )
    db_session.commit()


def _roles(db_session, map_id):
    rows = db_session.execute(
        select(MembershipRow.user_id, MembershipRow.role).where(MembershipRow.map_id == map_id)
    ).all()
    return dict(rows)


def _withdraw(db_session, user_id):
    db_session.execute(update(User).where(User.id == user_id).values(deleted_at=func.now()))
    db_session.commit()


def _events(db_session, map_id, type_):
    return db_session.execute(
        select(EventLog).where(EventLog.map_id == map_id, EventLog.type == type_)
    ).scalars().all()


def _pin(db_session, map_id, created_by="user_1"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct", place_id=f"p-{uuid.uuid4()}",
        geom=func.ST_SetSRID(func.ST_MakePoint(126.9, 37.5), 4326), visibility="public", created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _react(db_session, pin_id, user_id):
    db_session.add(ReactionRow(pin_id=pin_id, user_id=user_id, type="against", reason_text="별로"))
    db_session.commit()


def _evidence(db_session, map_id, author_id):
    run = RecommendRun(map_id=map_id, category="음식점", requested_by=author_id, status="collecting_evidence")
    db_session.add(run)
    db_session.flush()
    db_session.add(EvidenceLine(run_id=run.id, author_id=author_id, source="manual", text="조용한 곳", badge="preferred"))
    db_session.commit()
    return run.id


# --- 삭제 -----------------------------------------------------------------------------


def test_owner_deletes_map_and_it_disappears_for_every_member(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    token = _invite_token(app_client, map_id)

    resp = app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1"))
    assert resp.status_code == 204
    assert resp.content == b""

    for user_id in ("user_1", "user_2"):
        assert map_id not in [m["id"] for m in app_client.get("/maps", cookies=_auth(user_id)).json()]
        assert app_client.get(f"/maps/{map_id}", cookies=_auth(user_id)).status_code == 404
        assert app_client.get(f"/maps/{map_id}/pins", cookies=_auth(user_id)).status_code == 404
        assert app_client.get(f"/maps/{map_id}/members", cookies=_auth(user_id)).status_code == 404
    assert app_client.get(f"/invites/{token}").json()["code"] == "INVITE_NOT_FOUND"
    accept = app_client.post(f"/invites/{token}/accept", cookies=_auth("user_3"))
    assert (accept.status_code, accept.json()["code"]) == (404, "INVITE_NOT_FOUND")
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 404

    assert db_session.get(MapRow, map_id).deleted_at is not None   # soft delete — 행은 남는다
    [event] = _events(db_session, map_id, "map.deleted")
    assert (event.channel, event.payload) == ("public", {"map_id": map_id})


def test_member_cannot_delete_map_and_outsider_gets_404(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")

    forbidden = app_client.delete(f"/maps/{map_id}", cookies=_auth("user_2"))
    assert (forbidden.status_code, forbidden.json()["code"]) == (403, "FORBIDDEN")
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("outsider")).status_code == 404
    assert db_session.get(MapRow, map_id).deleted_at is None


def test_membership_gateway_treats_deleted_map_as_absent(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    gateway = DbMembershipGateway(db_session)
    assert gateway.current_member_ids(map_id) == {"user_1", "user_2"}

    app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1"))

    assert gateway.get_role(map_id, "user_1") is None
    assert gateway.current_member_ids(map_id) == set()


# --- 나가기 ---------------------------------------------------------------------------


def test_member_leaves_and_only_their_reactions_and_evidence_on_that_map_go(app_client, db_session):
    map_id = _create_map(app_client)
    other_map_id = _create_map(app_client, title="제주")
    _join(app_client, map_id, "user_2")
    token = _invite_token(app_client, other_map_id)
    app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2"))

    pin_by_leaver = _pin(db_session, map_id, created_by="user_2")
    _react(db_session, pin_by_leaver, "user_2")
    _react(db_session, pin_by_leaver, "user_1")
    other_pin = _pin(db_session, other_map_id)
    _react(db_session, other_pin, "user_2")
    run_here = _evidence(db_session, map_id, "user_2")
    _evidence(db_session, other_map_id, "user_2")

    resp = app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_2"))
    assert resp.status_code == 204

    assert _roles(db_session, map_id) == {"user_1": "owner"}
    reactions = db_session.execute(select(ReactionRow.pin_id, ReactionRow.user_id)).all()
    assert set(reactions) == {(pin_by_leaver, "user_1"), (other_pin, "user_2")}
    evidence = db_session.execute(select(EvidenceLine.run_id)).scalars().all()
    assert run_here not in evidence and len(evidence) == 1
    assert db_session.get(RecommendRun, run_here) is not None          # run은 남는다(#31 재시도 횟수)
    assert db_session.get(PinRow, pin_by_leaver).deleted_at is None    # 핀도 남는다

    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).status_code == 404
    assert map_id not in [m["id"] for m in app_client.get("/maps", cookies=_auth("user_2")).json()]
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["member_count"] == 1
    assert maps_api.count_members(db_session, map_id) == 1

    [event] = _events(db_session, map_id, "member.left")
    assert event.payload == {"map_id": map_id, "user_id": "user_2", "new_owner_user_id": None}


def test_rejoining_puts_the_member_at_the_back_of_the_line(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2", "user_3")
    _set_joined_at(db_session, map_id, ["user_1", "user_2", "user_3"])

    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_2")).status_code == 204
    _join(app_client, map_id, "user_2")
    rejoined_at = db_session.execute(
        select(MembershipRow.joined_at).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2")
    ).scalar_one()
    assert rejoined_at > T0 + timedelta(minutes=2)

    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204
    assert _roles(db_session, map_id) == {"user_2": "member", "user_3": "owner"}


def test_non_member_leaving_is_404(app_client):
    map_id = _create_map(app_client)
    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("outsider")).status_code == 404


# --- 위임 -----------------------------------------------------------------------------


def test_owner_leaving_hands_over_to_earliest_joined_non_withdrawn_member(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2", "user_3", "user_lonely")
    _set_joined_at(db_session, map_id, ["user_1", "user_2", "user_3", "user_lonely"])
    _withdraw(db_session, "user_2")

    detail = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert detail["next_owner"] == {"user_id": "user_3", "display_name": "user_3"}
    assert detail["permissions"] == {"can_delete": True, "can_leave": True}

    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204

    assert _roles(db_session, map_id) == {"user_2": "member", "user_3": "owner", "user_lonely": "member"}
    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_3")).json()
    assert [m["user_id"] for m in members if m["role"] == "owner"] == ["user_3"]
    [event] = _events(db_session, map_id, "member.left")
    assert event.payload == {"map_id": map_id, "user_id": "user_1", "new_owner_user_id": "user_3"}

    new_owner_view = app_client.get(f"/maps/{map_id}", cookies=_auth("user_3")).json()
    assert new_owner_view["permissions"] == {"can_delete": True, "can_leave": True}
    assert new_owner_view["next_owner"]["user_id"] == "user_lonely"


def test_member_list_role_follows_memberships_not_created_by(app_client, db_session):
    """#369 11번 — 위임 뒤 지도를 만든 사람이 다시 들어와도 owner로 보이지 않는다."""
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1"))
    _join_by(app_client, map_id, inviter="user_2", joiner="user_1")

    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1")).json()
    assert {m["user_id"]: m["role"] for m in members} == {"user_1": "member", "user_2": "owner"}
    accepted = _events(db_session, map_id, "member.joined")[-1]
    assert accepted.payload["role"] == "member"


def _join_by(app_client, map_id, *, inviter, joiner):
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth(inviter)).json()["token"]
    assert app_client.post(f"/invites/{token}/accept", cookies=_auth(joiner)).status_code == 200


def test_two_owners_on_one_map_is_impossible(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    with pytest.raises(IntegrityError):
        db_session.execute(
            update(MembershipRow)
            .where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2")
            .values(role="owner")
        )
    db_session.rollback()


# --- 넘길 사람이 없는 방장 ----------------------------------------------------------------


@pytest.mark.parametrize("others_withdrawn", [False, True])
def test_owner_without_successor_cannot_leave(app_client, db_session, others_withdrawn):
    map_id = _create_map(app_client)
    if others_withdrawn:
        _join(app_client, map_id, "user_2")
        _withdraw(db_session, "user_2")

    detail = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert detail["permissions"] == {"can_delete": True, "can_leave": False}
    assert "next_owner" not in detail

    resp = app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1"))
    assert (resp.status_code, resp.json()["code"]) == (409, "OWNER_CANNOT_LEAVE")
    assert _roles(db_session, map_id)["user_1"] == "owner"
    assert _events(db_session, map_id, "member.left") == []


def test_permissions_on_every_map_response(app_client):
    map_id = _create_map(app_client)
    token = _invite_token(app_client, map_id)

    created = app_client.post(
        "/maps", json={"title": "x", "start_date": "2026-10-10", "end_date": "2026-10-10"}, cookies=_auth("user_1")
    ).json()
    assert created["permissions"] == {"can_delete": True, "can_leave": False}
    accepted = app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2")).json()
    assert accepted["permissions"] == {"can_delete": False, "can_leave": True}

    listed = {m["id"]: m for m in app_client.get("/maps", cookies=_auth("user_1")).json()}
    assert listed[map_id]["permissions"] == {"can_delete": True, "can_leave": True}
    assert all("next_owner" not in m for m in listed.values())   # 목록에서는 생략
    member_view = app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()
    assert member_view["permissions"] == {"can_delete": False, "can_leave": True}
    assert "next_owner" not in member_view


# --- 탈퇴 -----------------------------------------------------------------------------


def test_withdrawing_owner_hands_over_or_deletes(app_client, db_session):
    shared = _create_map(app_client, title="함께")
    alone = _create_map(app_client, title="혼자")
    _join(app_client, shared, "user_2")

    maps_api.transfer_or_delete_owned_maps(db_session, "user_1")
    db_session.commit()

    assert _roles(db_session, shared) == {"user_1": "member", "user_2": "owner"}   # 행은 남긴다(#245)
    assert db_session.get(MapRow, alone).deleted_at is not None
    assert len(_events(db_session, alone, "map.deleted")) == 1
    assert db_session.get(MapRow, shared).deleted_at is None


# --- 내 지도 10개 상한 ------------------------------------------------------------------


def _fill_to_limit(app_client, user_id="user_2"):
    return [_create_map(app_client, user_id=user_id, title=f"지도 {i}") for i in range(10)]


def test_creating_an_eleventh_map_is_409(app_client):
    own = _fill_to_limit(app_client)
    resp = app_client.post(
        "/maps", json={"title": "하나 더", "start_date": "2026-10-10", "end_date": "2026-10-12"}, cookies=_auth("user_2")
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "MAP_LIMIT"
    assert resp.json()["detail"] == {"limit": 10, "count": 10}
    assert len(app_client.get("/maps", cookies=_auth("user_2")).json()) == len(own)


def test_accepting_a_new_invite_at_the_limit_is_409_but_rejoin_is_allowed(app_client):
    joined = _create_map(app_client, user_id="user_1", title="이미 참여")
    token_joined = _invite_token(app_client, joined)
    assert app_client.post(f"/invites/{token_joined}/accept", cookies=_auth("user_2")).status_code == 200
    for i in range(9):
        _create_map(app_client, user_id="user_2", title=f"지도 {i}")

    other = _create_map(app_client, user_id="user_1", title="새 초대")
    resp = app_client.post(f"/invites/{_invite_token(app_client, other)}/accept", cookies=_auth("user_2"))
    assert (resp.status_code, resp.json()["code"]) == (409, "MAP_LIMIT")
    assert app_client.post(f"/invites/{token_joined}/accept", cookies=_auth("user_2")).status_code == 200


@pytest.mark.parametrize("free_up", ["leave", "delete"])
def test_leaving_or_deleting_a_map_frees_a_slot(app_client, free_up):
    joined = _create_map(app_client, user_id="user_1", title="참여한 지도")
    _join(app_client, joined, "user_2")
    own = [_create_map(app_client, user_id="user_2", title=f"지도 {i}") for i in range(9)]

    if free_up == "leave":
        assert app_client.delete(f"/maps/{joined}/members/me", cookies=_auth("user_2")).status_code == 204
    else:
        assert app_client.delete(f"/maps/{own[0]}", cookies=_auth("user_2")).status_code == 204
    _create_map(app_client, user_id="user_2", title="이제 된다")

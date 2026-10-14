"""
초대 링크 목록·끄기·재사용(#467) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from common.errors import AppError
from maps.core import InviteRecord, check_invite_acceptable, pick_reusable_invite
from maps.models import Invite as InviteRow
from maps.models import Membership as MembershipRow
from maps.tests.test_delete_leave_api import _auth, _create_map, _join, _withdraw

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _invite(app_client, map_id, user_id="user_1"):
    return app_client.post(f"/maps/{map_id}/invite", cookies=_auth(user_id))


def _list(app_client, map_id, user_id="user_1"):
    return app_client.get(f"/maps/{map_id}/invites", cookies=_auth(user_id))


def _revoke(app_client, token, user_id="user_1"):
    return app_client.delete(f"/invites/{token}", cookies=_auth(user_id))


# ---- POST /maps/{id}/invite — 재사용 ----

def test_invite_is_created_once_then_reused_with_200(app_client, db_session):
    map_id = _create_map(app_client)
    first = _invite(app_client, map_id)
    again = _invite(app_client, map_id)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json() == again.json()
    assert len(db_session.execute(select(InviteRow).where(InviteRow.map_id == map_id)).all()) == 1


def test_another_members_link_is_not_reused(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    owners = _invite(app_client, map_id, "user_1").json()
    theirs = _invite(app_client, map_id, "user_2")
    assert theirs.status_code == 201
    assert theirs.json()["token"] != owners["token"]


def test_revoked_or_expired_link_is_not_reused(app_client, db_session):
    map_id = _create_map(app_client)
    token = _invite(app_client, map_id).json()["token"]
    assert _revoke(app_client, token).status_code == 204
    second = _invite(app_client, map_id)
    assert second.status_code == 201 and second.json()["token"] != token

    db_session.execute(
        update(InviteRow).where(InviteRow.token == second.json()["token"])
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    db_session.commit()
    third = _invite(app_client, map_id)
    assert third.status_code == 201 and third.json()["token"] != second.json()["token"]


# ---- GET /maps/{id}/invites ----

def test_list_returns_live_links_newest_first_with_details(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    older = _invite(app_client, map_id, "user_1").json()  # _join이 만든 링크와 같은 링크다(재사용) — user_2가 이미 한 번 썼다
    newer = _invite(app_client, map_id, "user_2").json()
    db_session.execute(update(InviteRow).where(InviteRow.token == older["token"]).values(created_at=NOW))
    db_session.execute(
        update(InviteRow).where(InviteRow.token == newer["token"]).values(created_at=NOW + timedelta(hours=1))
    )
    db_session.commit()
    assert app_client.post(f"/invites/{older['token']}/accept", cookies=_auth("user_3")).status_code == 200

    resp = _list(app_client, map_id)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert [i["token"] for i in items] == [newer["token"], older["token"]]
    assert all(i["url"].endswith(f"/invites/{i['token']}") for i in items)
    assert [i["used_count"] for i in items] == [0, 2]  # older: user_2(_join) + user_3
    assert all(i["created_at"] and i["created_by_display_name"] for i in items)


def test_list_hides_revoked_and_expired_and_is_empty_when_none(app_client, db_session):
    map_id = _create_map(app_client)
    assert _list(app_client, map_id).json() == []
    live = _invite(app_client, map_id).json()
    db_session.add(InviteRow(token="expired-tok-1234567890", map_id=map_id, created_by="user_1",
                             expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    db_session.add(InviteRow(token="revoked-tok-1234567890", map_id=map_id, created_by="user_1",
                             expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                             revoked_at=datetime.now(timezone.utc)))
    db_session.commit()
    assert [i["token"] for i in _list(app_client, map_id).json()] == [live["token"]]


def test_list_shows_withdrawn_creator_as_masked_name(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    token = _invite(app_client, map_id, "user_2").json()["token"]
    _withdraw(db_session, "user_2")
    by_token = {i["token"]: i for i in _list(app_client, map_id).json()}
    assert by_token[token]["created_by_display_name"] == "탈퇴한 구성원"
    assert all(i["created_by_display_name"] != "탈퇴한 구성원" for t, i in by_token.items() if t != token)


def test_list_permissions_owner_only(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert _list(app_client, map_id, "user_2").status_code == 403
    assert _list(app_client, map_id, "outsider").status_code == 404
    assert app_client.get(f"/maps/{map_id}/invites").status_code == 401


# ---- DELETE /invites/{token} ----

def test_owner_revokes_then_summary_and_accept_are_410_revoked(app_client, db_session):
    map_id = _create_map(app_client)
    token = _invite(app_client, map_id).json()["token"]
    assert _revoke(app_client, token).status_code == 204

    summary = app_client.get(f"/invites/{token}")
    assert (summary.status_code, summary.json()["code"]) == (410, "INVITE_REVOKED")
    accept = app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2"))
    assert (accept.status_code, accept.json()["code"]) == (410, "INVITE_REVOKED")
    assert db_session.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2")
    ).first() is None
    assert _list(app_client, map_id).json() == []


def test_revoke_is_idempotent_and_keeps_the_first_revoked_at(app_client, db_session):
    map_id = _create_map(app_client)
    token = _invite(app_client, map_id).json()["token"]
    assert _revoke(app_client, token).status_code == 204
    first = db_session.execute(select(InviteRow.revoked_at).where(InviteRow.token == token)).scalar_one()
    assert first is not None
    assert _revoke(app_client, token).status_code == 204
    db_session.expire_all()
    assert db_session.execute(select(InviteRow.revoked_at).where(InviteRow.token == token)).scalar_one() == first


def test_revoking_keeps_people_who_already_joined(app_client):
    map_id = _create_map(app_client)
    token = _invite(app_client, map_id).json()["token"]
    assert app_client.post(f"/invites/{token}/accept", cookies=_auth("user_2")).status_code == 200
    assert _revoke(app_client, token).status_code == 204
    assert len(app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1")).json()) == 2


def test_revoke_permissions(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    token = _invite(app_client, map_id, "user_2").json()["token"]  # 구성원이 만든 링크라도 끄는 건 방장만
    assert _revoke(app_client, token, "user_2").status_code == 403
    assert _revoke(app_client, token, "outsider").status_code == 404
    assert app_client.delete(f"/invites/{token}").status_code == 401
    assert db_session.execute(select(InviteRow.revoked_at).where(InviteRow.token == token)).scalar_one() is None
    assert _revoke(app_client, token, "user_1").status_code == 204  # 방장은 남이 만든 링크도 끈다


def test_revoke_unknown_token_or_deleted_map_is_404(app_client):
    map_id = _create_map(app_client)
    token = _invite(app_client, map_id).json()["token"]
    assert _revoke(app_client, "no-such-token-1234567890").status_code == 404
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    resp = _revoke(app_client, token)
    assert (resp.status_code, resp.json()["code"]) == (404, "INVITE_NOT_FOUND")


def test_revoke_follows_the_current_owner_not_the_link_creator(app_client):
    """방장 권한은 지금의 memberships.role로 본다 — 링크를 만든 사람이 아니라."""
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    token = _invite(app_client, map_id, "user_1").json()["token"]
    assert app_client.delete(f"/maps/{map_id}/members/me", cookies=_auth("user_1")).status_code == 204
    assert _revoke(app_client, token, "user_1").status_code == 404  # 나간 사람은 비구성원
    assert _revoke(app_client, token, "user_2").status_code == 204  # 새 방장


# ---- core ----

def _rec(token, by="u1", created=NOW, expires=NOW + timedelta(days=7), revoked=None):
    return InviteRecord(
        token=token, created_by=by, created_at=created, expires_at=expires, revoked_at=revoked, used_count=0
    )


def test_pick_reusable_prefers_my_latest_live_link():
    invites = [
        _rec("old", created=NOW - timedelta(hours=2)),
        _rec("new", created=NOW - timedelta(hours=1)),
        _rec("others", by="u2", created=NOW),
        _rec("revoked", created=NOW, revoked=NOW),
        _rec("expired", created=NOW, expires=NOW - timedelta(seconds=1)),
    ]
    assert pick_reusable_invite(invites, "u1", NOW).token == "new"
    assert pick_reusable_invite(invites, "nobody", NOW) is None


def test_revoked_wins_over_expired_in_acceptability():
    past = NOW - timedelta(days=1)
    with pytest.raises(AppError) as err:
        check_invite_acceptable(past, NOW, revoked_at=past)
    assert err.value.code == "INVITE_REVOKED"
    with pytest.raises(AppError) as err:
        check_invite_acceptable(past, NOW)
    assert err.value.code == "INVITE_EXPIRED"

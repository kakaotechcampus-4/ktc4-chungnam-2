"""POST /maps/{mapId}/seen(#1556) — 구성원의 「마지막으로 본 때」를 서버 시각으로 적는다."""

from sqlalchemy import select

from common.events import EventLog
from maps.models import Membership as MembershipRow
from maps.tests.test_delete_leave_api import _auth, _create_map, _join


def _last_seen(db_session, map_id, user_id):
    db_session.expire_all()
    return db_session.execute(
        select(MembershipRow.last_seen_at).where(MembershipRow.map_id == map_id, MembershipRow.user_id == user_id)
    ).scalar_one()


def test_new_membership_has_no_last_seen(app_client, db_session):
    map_id = _create_map(app_client)
    assert _last_seen(db_session, map_id, "user_1") is None


def test_seen_sets_my_time_only_and_sends_no_event(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")

    resp = app_client.post(f"/maps/{map_id}/seen", cookies=_auth("user_2"))
    assert resp.status_code == 204 and resp.content == b""

    assert _last_seen(db_session, map_id, "user_2") is not None
    assert _last_seen(db_session, map_id, "user_1") is None   # 다른 사람 것은 그대로
    assert db_session.execute(select(EventLog).where(EventLog.map_id == map_id, EventLog.type.like("%seen%"))).first() is None


def test_seen_again_moves_the_time_forward(app_client, db_session):
    map_id = _create_map(app_client)
    app_client.post(f"/maps/{map_id}/seen", cookies=_auth("user_1"))
    first = _last_seen(db_session, map_id, "user_1")
    app_client.post(f"/maps/{map_id}/seen", cookies=_auth("user_1"))
    assert _last_seen(db_session, map_id, "user_1") >= first


def test_seen_non_member_404_anonymous_401_deleted_map_404(app_client, db_session):
    map_id = _create_map(app_client)
    assert app_client.post(f"/maps/{map_id}/seen", cookies=_auth("outsider")).status_code == 404
    assert app_client.post(f"/maps/{map_id}/seen").status_code == 401
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    assert app_client.post(f"/maps/{map_id}/seen", cookies=_auth("user_1")).status_code == 404

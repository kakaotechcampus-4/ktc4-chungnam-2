"""POST /maps/{mapId}/seen(#1556) — 구성원의 「마지막으로 본 때」를 서버 시각으로 적는다."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select

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


def test_seen_time_comes_from_the_database_clock_not_the_app(app_client, db_session):
    """/news가 비교하는 핀·반응의 created_at·updated_at은 DB now()다 — 앱 시각이 섞이면 시계가 어긋나 새 소식이 새거나 빠진다(#1556).
    그래서 UPDATE가 시각을 바인딩 값으로 받지 않고 SQL의 now()로 적는지 본다."""
    map_id = _create_map(app_client)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE MEMBERSHIPS") and "last_seen_at" in statement:
            statements.append((statement, parameters))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert app_client.post(f"/maps/{map_id}/seen", cookies=_auth("user_1")).status_code == 204
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    [(statement, parameters)] = statements
    assert "now()" in statement.lower()
    assert not any(hasattr(v, "tzinfo") for v in (parameters.values() if isinstance(parameters, dict) else parameters))


def test_seen_at_from_news_is_kept_so_later_news_stays_new(app_client, db_session):
    """#1672 — 화면은 본 새 소식의 as_of 를 seen_at 으로 돌려준다. 조회 뒤 확인 전에 생긴 것을 본 것으로 적지 않는다."""
    map_id = _create_map(app_client)
    as_of = app_client.get(f"/maps/{map_id}/news", cookies=_auth("user_1")).json()["as_of"]
    assert app_client.post(f"/maps/{map_id}/seen", json={"seen_at": as_of}, cookies=_auth("user_1")).status_code == 204
    assert _last_seen(db_session, map_id, "user_1").isoformat() == datetime.fromisoformat(as_of).isoformat()


def test_seen_at_in_the_future_is_cut_to_now_and_never_moves_back(app_client, db_session):
    map_id = _create_map(app_client)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert app_client.post(f"/maps/{map_id}/seen", json={"seen_at": future}, cookies=_auth("user_1")).status_code == 204
    now_ish = _last_seen(db_session, map_id, "user_1")
    assert now_ish < datetime.now(timezone.utc) + timedelta(minutes=1)

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert app_client.post(f"/maps/{map_id}/seen", json={"seen_at": past}, cookies=_auth("user_1")).status_code == 204
    assert _last_seen(db_session, map_id, "user_1") == now_ish   # 다른 기기가 더 늦게 적었으면 되돌리지 않는다


def test_seen_at_must_be_a_datetime(app_client):
    map_id = _create_map(app_client)
    assert app_client.post(f"/maps/{map_id}/seen", json={"seen_at": "어제"}, cookies=_auth("user_1")).status_code == 422

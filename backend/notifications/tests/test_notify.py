"""api.notify — 만들기와 거르기(행위자 본인, 꺼 둔 종류), delete_by_user, purge_old."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from notifications import api, service
from notifications.models import Notification, NotificationPref


def _count(db, **where) -> int:
    q = select(func.count()).select_from(Notification)
    for column, value in where.items():
        q = q.where(getattr(Notification, column) == value)
    return db.execute(q).scalar_one()


def _notify(db, **override):
    args = dict(user_id="u1", type="pin_reaction", map_id="m1", map_title="부산", message="x", pin_id="p1")
    return api.notify(db, **{**args, **override})


def test_creates_one_row_per_call(db_session):
    nid = _notify(db_session)
    assert nid is not None
    row = db_session.get(Notification, nid)
    assert (row.user_id, row.type, row.map_id, row.map_title, row.pin_id, row.message, row.read_at) == (
        "u1", "pin_reaction", "m1", "부산", "p1", "x", None,
    )
    assert row.created_at is not None


def test_does_not_commit(db_session):
    _notify(db_session)
    db_session.rollback()      # 호출자가 롤백하면 알림도 같이 사라진다 — 같은 트랜잭션에 참여한다
    assert _count(db_session) == 0


def test_skips_the_actor_themselves(db_session):
    assert _notify(db_session, user_id="u1", actor_id="u1") is None
    assert _count(db_session) == 0
    assert _notify(db_session, user_id="u1", actor_id="u2") is not None
    assert _notify(db_session, user_id="u1", actor_id=None) is not None   # 행위자를 모르면(시스템 이벤트) 거르지 않는다
    assert _count(db_session) == 2


def test_skips_a_type_the_recipient_turned_off(db_session):
    db_session.add(NotificationPref(user_id="u1", type="pin_reaction", enabled=False))
    db_session.flush()
    assert _notify(db_session, type="pin_reaction") is None
    assert _notify(db_session, type="member_joined", pin_id=None) is not None     # 다른 종류는 그대로
    assert _notify(db_session, user_id="u2", type="pin_reaction") is not None     # 다른 사람 설정은 영향 없음
    assert _count(db_session) == 2


def test_an_explicit_enabled_row_still_notifies(db_session):
    db_session.add(NotificationPref(user_id="u1", type="pin_reaction", enabled=True))
    db_session.flush()
    assert _notify(db_session) is not None


def test_unknown_type_raises(db_session):
    with pytest.raises(ValueError):
        _notify(db_session, type="pin_deleted")


def test_long_message_and_title_are_clipped_to_the_spec_limits(db_session):
    row = db_session.get(Notification, _notify(db_session, message="가" * 500, map_title="나" * 500))
    assert len(row.message) == 200 and len(row.map_title) == 100


def test_title_is_optional(db_session):
    row = db_session.get(Notification, _notify(db_session, map_title=None, pin_id=None))
    assert row.map_title is None and row.pin_id is None


def test_compose_message_is_exposed_for_other_modules():
    assert api.compose_message("member_joined", actor_name="지우") == "지우님이 지도에 들어왔어요"


def test_delete_by_user_removes_only_that_users_rows(db_session):
    _notify(db_session, user_id="gone")
    _notify(db_session, user_id="gone", type="member_joined")
    _notify(db_session, user_id="stays")
    service.update_prefs(db_session, user_id="gone", updates=[("pin_reaction", False)])
    service.update_prefs(db_session, user_id="stays", updates=[("pin_reaction", False)])

    assert api.delete_by_user(db_session, user_id="gone") == {"notifications": 2, "notification_prefs": 1}
    assert (_count(db_session, user_id="gone"), _count(db_session, user_id="stays")) == (0, 1)
    assert service.get_prefs(db_session, user_id="stays").prefs[0].enabled is False
    assert api.delete_by_user(db_session, user_id="gone") == {"notifications": 0, "notification_prefs": 0}   # 멱등


def test_purge_old_deletes_past_ninety_days_regardless_of_read_state_or_map(db_session):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    old_unread = db_session.get(Notification, _notify(db_session, map_id="deleted-map"))
    old_read = db_session.get(Notification, _notify(db_session))
    fresh = db_session.get(Notification, _notify(db_session))
    edge = db_session.get(Notification, _notify(db_session))
    old_unread.created_at = now - timedelta(days=91)
    old_read.created_at = now - timedelta(days=200)
    old_read.read_at = now - timedelta(days=199)
    fresh.created_at = now - timedelta(days=10)
    edge.created_at = now - timedelta(days=90)           # 정확히 90일은 아직 남긴다
    db_session.flush()
    service.update_prefs(db_session, user_id="u1", updates=[("pin_reaction", False)])

    assert api.purge_old(db_session, now=now) == {"notifications": 2}
    assert set(db_session.execute(select(Notification.id)).scalars()) == {fresh.id, edge.id}
    assert len(service.get_prefs(db_session, user_id="u1").prefs) == 5                  # 설정은 그대로
    assert api.purge_old(db_session, now=now, older_than_days=5) == {"notifications": 2}   # 기간을 바꿀 수 있다

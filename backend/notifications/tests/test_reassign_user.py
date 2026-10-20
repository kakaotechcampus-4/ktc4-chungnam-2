"""api.reassign_user(#560) — 게스트의 알림은 to_user로 옮기고, 알림 설정은 to_user의 값이 이긴다."""

from datetime import datetime, timezone

from sqlalchemy import select

from notifications import api
from notifications.models import Notification, NotificationPref


def _notify(db, user_id, type="pin_reaction", message="x"):
    return api.notify(db, user_id=user_id, type=type, map_id="m1", map_title="부산", message=message, pin_id="p1")


def _owners(db):
    return {n.id: n.user_id for n in db.execute(select(Notification)).scalars()}


def _prefs(db, user_id):
    return dict(db.execute(select(NotificationPref.type, NotificationPref.enabled)
                           .where(NotificationPref.user_id == user_id)).all())


def test_moves_notifications_keeping_read_state_time_and_message(db_session):
    unread = _notify(db_session, "guest", message="안 읽음")
    read = _notify(db_session, "guest", type="member_joined", message="읽음")
    other = _notify(db_session, "other")
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    row = db_session.get(Notification, read)
    row.read_at, row.created_at = stamp, stamp
    before = {n.id: (n.created_at, n.read_at, n.message) for n in db_session.execute(select(Notification)).scalars()}
    db_session.flush()

    result = api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert result["notifications"] == 2
    assert _owners(db_session) == {unread: "kakao", read: "kakao", other: "other"}   # 다른 사용자 알림은 그대로
    db_session.expire_all()
    after = {n.id: (n.created_at, n.read_at, n.message) for n in db_session.execute(select(Notification)).scalars()}
    assert after == before


def test_prefs_keep_to_user_values_on_conflict(db_session):
    db_session.add_all([
        NotificationPref(user_id="guest", type="pin_reaction", enabled=False),    # 양쪽에 있다 — 카카오 값(켜짐)이 이긴다
        NotificationPref(user_id="kakao", type="pin_reaction", enabled=True),
        NotificationPref(user_id="guest", type="member_joined", enabled=False),   # 게스트에만 있다 — 옮긴다
        NotificationPref(user_id="guest", type="map_deleted", enabled=False),     # 카카오에 켜짐이 있다 — 카카오 값이 이긴다
        NotificationPref(user_id="kakao", type="map_deleted", enabled=True),
    ])
    db_session.flush()

    result = api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert result["notification_prefs"] == 1
    assert _prefs(db_session, "kakao") == {"pin_reaction": True, "member_joined": False, "map_deleted": True}
    assert _prefs(db_session, "guest") == {}


def test_to_user_off_pref_is_not_overwritten_by_guest_on(db_session):
    db_session.add_all([
        NotificationPref(user_id="guest", type="pin_reaction", enabled=True),
        NotificationPref(user_id="kakao", type="pin_reaction", enabled=False),
    ])
    db_session.flush()

    api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert _prefs(db_session, "kakao") == {"pin_reaction": False}


def test_idempotent(db_session):
    _notify(db_session, "guest")
    db_session.add(NotificationPref(user_id="guest", type="pin_reaction", enabled=False))
    db_session.flush()
    api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao") == {
        "notifications": 0, "notification_prefs": 0}
    assert _prefs(db_session, "kakao") == {"pin_reaction": False}
    assert list(_owners(db_session).values()) == ["kakao"]


def test_same_id_changes_nothing(db_session):
    _notify(db_session, "u1")
    db_session.add(NotificationPref(user_id="u1", type="pin_reaction", enabled=False))
    db_session.flush()

    assert api.reassign_user(db_session, from_user_id="u1", to_user_id="u1") == {
        "notifications": 0, "notification_prefs": 0}
    assert list(_owners(db_session).values()) == ["u1"]
    assert _prefs(db_session, "u1") == {"pin_reaction": False}

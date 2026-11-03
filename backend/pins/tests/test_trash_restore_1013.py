"""#1013 — POST /pins/{pinId}/restore: 찍은 사람과 방장이 30일 안의 지운 핀을 되살린다."""

from datetime import datetime, timedelta, timezone

import authz.deps
from authz.testing import FakeMembership
from main import app
from pins.models import Pin as PinRow
from pins.tests.test_pins_api import _auth, _insert_pin


def _roles(**roles):
    app.dependency_overrides[authz.deps.get_membership_gateway] = lambda: FakeMembership(
        {tuple(key.split("__")): role for key, role in roles.items()}
    )


def _trashed(db_session, *, days_ago: float = 1, created_by="user_1", deleted_by="user_1", confirmed=False, place_id=None):
    row = _insert_pin(db_session, created_by=created_by, place_id=place_id)
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    row.deleted_by = deleted_by
    row.deleted_was_confirmed = confirmed
    db_session.commit()
    return row


def _restore(app_client, pin, user="user_1"):
    return app_client.post(f"/pins/{pin.id}/restore", cookies=_auth(user))


def test_author_restores_own_pin_and_the_deleted_record_is_cleared(app_client, db_session):
    pin = _trashed(db_session)
    res = _restore(app_client, pin)
    assert res.status_code == 200 and res.json()["id"] == str(pin.id)
    db_session.expire_all()
    row = db_session.get(PinRow, pin.id)
    assert (row.deleted_at, row.deleted_by, row.deleted_was_confirmed) == (None, None, None)


def test_restore_is_idempotent(app_client, db_session):
    pin = _trashed(db_session)
    assert _restore(app_client, pin).status_code == 200
    assert _restore(app_client, pin).status_code == 200


def test_owner_restores_someone_elses_pin(app_client, db_session):
    _roles(map_1__user_1="owner", map_1__user_2="member")
    pin = _trashed(db_session, created_by="user_2", deleted_by="user_2")
    assert _restore(app_client, pin, "user_1").status_code == 200


def test_member_cannot_restore_someone_elses_trashed_pin_and_does_not_learn_it_exists(app_client, db_session):
    _roles(map_1__user_1="owner", map_1__user_2="member")
    pin = _trashed(db_session, created_by="user_1")
    assert _restore(app_client, pin, "user_2").status_code == 404
    db_session.expire_all()
    assert db_session.get(PinRow, pin.id).deleted_at is not None


def test_member_gets_403_for_someone_elses_live_pin(app_client, db_session):
    _roles(map_1__user_1="owner", map_1__user_2="member")
    pin = _insert_pin(db_session, created_by="user_1")
    assert _restore(app_client, pin, "user_2").status_code == 403


def test_non_member_missing_and_expired_pins_are_404(app_client, db_session):
    other_map = _insert_pin(db_session, map_id="map_9")
    other_map.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    assert _restore(app_client, other_map).status_code == 404       # user_1은 map_9의 구성원이 아니다
    assert app_client.post("/pins/00000000-0000-0000-0000-000000000000/restore", cookies=_auth()).status_code == 404
    assert app_client.post("/pins/not-a-uuid/restore", cookies=_auth()).status_code == 404
    expired = _trashed(db_session, days_ago=30.1)   # 같은 지도, 찍은 사람
    assert _restore(app_client, expired).status_code == 404


def test_restoring_while_a_new_pin_took_the_place_is_409_with_the_existing_pin(app_client, db_session):
    old = _trashed(db_session, place_id="place_same")
    new = _insert_pin(db_session, place_id="place_same")
    res = _restore(app_client, old)
    assert res.status_code == 409 and res.json()["detail"]["pin_id"] == str(new.id)
    db_session.expire_all()
    assert db_session.get(PinRow, old.id).deleted_at is not None


def test_confirmed_pin_goes_back_to_the_shortlist_before_the_event_is_made(app_client, db_session, monkeypatch):
    calls = []

    def fake_restore_confirmed(db, *, pin_id):
        row = db.get(PinRow, __import__("uuid").UUID(pin_id))
        assert row.deleted_at is None          # 핀이 먼저 되살아난 뒤에 부른다
        row.kind = "확정"
        db.flush()
        calls.append(pin_id)
        return True

    monkeypatch.setattr("shortlist.api.restore_confirmed", fake_restore_confirmed)
    pin = _trashed(db_session, confirmed=True)
    res = _restore(app_client, pin)
    assert res.status_code == 200 and calls == [str(pin.id)]
    assert res.json()["kind"] == "확정"


def test_unconfirmed_pin_does_not_touch_the_shortlist(app_client, db_session, monkeypatch):
    monkeypatch.setattr("shortlist.api.restore_confirmed", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert _restore(app_client, _trashed(db_session)).status_code == 200


def test_restore_records_pin_restored_event_only_the_first_time(app_client, db_session):
    from common.events import EventLog as EventRow
    pin = _trashed(db_session)
    _restore(app_client, pin)
    _restore(app_client, pin)
    types = [e.type for e in db_session.query(EventRow).all()]
    assert types.count("pin.restored") == 1

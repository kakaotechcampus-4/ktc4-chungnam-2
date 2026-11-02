"""#1013 — 핀 삭제는 휴지통으로 옮기는 것이다: 삭제한 사람·확정 여부를 남기고, 30일 지난 핀만 정리한다."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

import authz.deps
from authz.testing import FakeMembership
from main import app
from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import _auth, _insert_pin

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _trash(db_session, *, days_ago: float, **kw) -> PinRow:
    row = _insert_pin(db_session, **kw)
    row.deleted_at = NOW - timedelta(days=days_ago)
    db_session.commit()
    return row


def test_delete_records_who_and_that_it_was_not_confirmed(app_client, db_session):
    pin = _insert_pin(db_session, created_by="user_1")
    assert app_client.delete(f"/pins/{pin.id}", cookies=_auth("user_1")).status_code == 204
    db_session.expire_all()
    row = db_session.get(PinRow, pin.id)
    assert row.deleted_at is not None and row.deleted_by == "user_1" and row.deleted_was_confirmed is False


def test_owner_deleting_someone_elses_pin_is_recorded_as_the_deleter(app_client, db_session):
    app.dependency_overrides[authz.deps.get_membership_gateway] = lambda: FakeMembership(
        {("map_1", "user_1"): "owner", ("map_1", "user_2"): "member"})
    pin = _insert_pin(db_session, created_by="user_2")
    assert app_client.delete(f"/pins/{pin.id}", cookies=_auth("user_1")).status_code == 204   # user_1은 방장
    db_session.expire_all()
    assert db_session.get(PinRow, pin.id).deleted_by == "user_1"


def test_delete_remembers_that_the_pin_was_confirmed(app_client, db_session, monkeypatch):
    monkeypatch.setattr("shortlist.api.remove_for_deleted_pin", lambda db, **kw: True)
    pin = _insert_pin(db_session)
    assert app_client.delete(f"/pins/{pin.id}", cookies=_auth()).status_code == 204
    db_session.expire_all()
    assert db_session.get(PinRow, pin.id).deleted_was_confirmed is True


def test_purge_removes_only_pins_past_thirty_days_with_their_reactions(db_session):
    old = _trash(db_session, days_ago=31)
    edge = _trash(db_session, days_ago=30)          # 정확히 30일이면 지난 것으로 본다
    fresh = _trash(db_session, days_ago=29.9)
    alive = _insert_pin(db_session)
    db_session.add(ReactionRow(pin_id=old.id, user_id="user_2", type="like"))
    db_session.commit()

    counts = pins_api.purge_deleted_pins(db_session, now=NOW)
    db_session.commit()

    assert counts == {"reactions": 1, "pins": 2}
    left = set(db_session.execute(select(PinRow.id)).scalars())
    assert left == {fresh.id, alive.id}
    assert db_session.execute(select(func.count()).select_from(ReactionRow)).scalar_one() == 0


def test_purge_is_idempotent_and_batch_limited(db_session, monkeypatch):
    monkeypatch.setattr("pins.core.PURGE_BATCH_LIMIT", 2)
    for _ in range(3):
        _trash(db_session, days_ago=40)
    assert pins_api.purge_deleted_pins(db_session, now=NOW)["pins"] == 2
    db_session.commit()
    assert pins_api.purge_deleted_pins(db_session, now=NOW)["pins"] == 1
    db_session.commit()
    assert pins_api.purge_deleted_pins(db_session, now=NOW) == {"reactions": 0, "pins": 0}


def test_reassign_user_moves_the_deleter_too(db_session):
    row = _trash(db_session, days_ago=1, created_by="user_9")
    row.deleted_by = "guest_1"
    db_session.commit()
    pins_api.reassign_user(db_session, from_user_id="guest_1", to_user_id="user_1")
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(PinRow, row.id).deleted_by == "user_1"

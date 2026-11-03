"""#1013 — 핀 삭제는 휴지통으로 옮기는 것이다: 삭제한 사람·확정 여부를 남기고, 30일 지난 핀만 정리한다."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

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


def test_purge_rejects_naive_now_and_deletes_nothing(db_session):
    old = _trash(db_session, days_ago=40)
    with pytest.raises(ValueError):
        pins_api.purge_deleted_pins(db_session, now=NOW.replace(tzinfo=None))
    assert db_session.get(PinRow, old.id) is not None


def test_purge_boundary_is_the_same_instant_for_a_non_utc_now(db_session):
    kst = timezone(timedelta(hours=9))
    deleted_at = NOW - timedelta(days=10)
    keep, gone = _insert_pin(db_session), _insert_pin(db_session)
    keep.deleted_at = deleted_at
    gone.deleted_at = deleted_at
    db_session.commit()
    keep_id, gone_id = keep.id, gone.id
    before = (deleted_at + timedelta(days=30) - timedelta(minutes=1)).astimezone(kst)    # 29일 23시간 59분 뒤
    assert pins_api.purge_deleted_pins(db_session, now=before) == {"reactions": 0, "pins": 0}
    assert db_session.get(PinRow, keep_id) is not None
    at = (deleted_at + timedelta(days=30)).astimezone(kst)                                  # 30일 뒤
    assert pins_api.purge_deleted_pins(db_session, now=at)["pins"] == 2
    db_session.expire_all()
    assert db_session.get(PinRow, gone_id) is None


def test_purge_is_idempotent_and_batch_limited(db_session, monkeypatch):
    monkeypatch.setattr("pins.core.PURGE_BATCH_LIMIT", 2)
    newest = _trash(db_session, days_ago=31)
    for age in (40, 35):
        _trash(db_session, days_ago=age)
    assert pins_api.purge_deleted_pins(db_session, now=NOW)["pins"] == 2
    db_session.commit()
    assert set(db_session.scalars(select(PinRow.id))) == {newest.id}
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


@pytest.fixture
def committed_trash(test_engine):
    # 두 연결에서 볼 수 있게 실제 커밋한다. savepoint 픽스처와 섞지 않는다.
    with Session(test_engine) as db:
        row = _trash(db, days_ago=31)
        pin_id = row.id
        db.add(ReactionRow(pin_id=pin_id, user_id="user_2", type="like"))
        db.commit()
    try:
        yield pin_id
    finally:
        with test_engine.begin() as conn:
            conn.execute(delete(ReactionRow).where(ReactionRow.pin_id == pin_id))
            conn.execute(delete(PinRow).where(PinRow.id == pin_id))


def test_restore_between_purge_select_and_delete_cannot_lose_pin_or_reactions(
    test_engine, committed_trash, monkeypatch,
):
    """실제 SELECT 직후 별도 트랜잭션의 복구 UPDATE를 실행한다. 조회 행은 commit까지 잠겨야 한다."""
    pin_id = committed_trash
    restore_blocked = False
    with Session(test_engine) as purge_db:
        execute = purge_db.execute

        def execute_then_restore(statement, *args, **kwargs):
            nonlocal restore_blocked
            result = execute(statement, *args, **kwargs)
            if statement.is_select:
                with Session(test_engine) as restore_db:
                    restore_db.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    try:
                        restore_db.execute(update(PinRow).where(PinRow.id == pin_id).values(
                            deleted_at=None, deleted_by=None, deleted_was_confirmed=None,
                        ))
                        restore_db.commit()
                    except OperationalError as exc:
                        assert exc.orig.pgcode == "55P03"  # lock_not_available
                        restore_db.rollback()
                        restore_blocked = True
            return result

        monkeypatch.setattr(purge_db, "execute", execute_then_restore)
        counts = pins_api.purge_deleted_pins(purge_db, now=NOW)
        purge_db.commit()
    with Session(test_engine) as db:
        if restore_blocked:
            assert counts == {"reactions": 1, "pins": 1}
            assert db.get(PinRow, pin_id) is None
        else:
            assert counts == {"reactions": 0, "pins": 0}
            assert db.get(PinRow, pin_id).deleted_at is None
            assert db.scalar(select(func.count()).select_from(ReactionRow)) == 1


def test_purge_skips_pin_while_restore_holds_lock(test_engine, committed_trash):
    pin_id = committed_trash
    with Session(test_engine) as restore_db, Session(test_engine) as purge_db:
        restore_db.execute(update(PinRow).where(PinRow.id == pin_id).values(
            deleted_at=None, deleted_by=None, deleted_was_confirmed=None,
        ))
        purge_db.execute(text("SET LOCAL statement_timeout = '2s'"))
        assert pins_api.purge_deleted_pins(purge_db, now=NOW) == {"reactions": 0, "pins": 0}
        purge_db.commit()
        restore_db.commit()
    with Session(test_engine) as db:
        assert pins_api.purge_deleted_pins(db, now=NOW) == {"reactions": 0, "pins": 0}
        assert db.get(PinRow, pin_id).deleted_at is None
        assert db.scalar(select(func.count()).select_from(ReactionRow)) == 1


def test_purge_rollback_preserves_pin_and_reactions_and_releases_lock(test_engine, committed_trash):
    with Session(test_engine) as purge_db:
        assert pins_api.purge_deleted_pins(purge_db, now=NOW) == {"reactions": 1, "pins": 1}
        purge_db.rollback()
    with Session(test_engine) as restore_db:
        restore_db.execute(text("SET LOCAL lock_timeout = '200ms'"))
        assert restore_db.execute(update(PinRow).where(PinRow.id == committed_trash).values(
            deleted_at=None, deleted_by=None, deleted_was_confirmed=None,
        )).rowcount == 1
        restore_db.commit()
        assert restore_db.get(PinRow, committed_trash).deleted_at is None
        assert restore_db.scalar(select(func.count()).select_from(ReactionRow)) == 1

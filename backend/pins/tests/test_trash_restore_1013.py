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


def test_member_gets_404_for_someone_elses_live_pin(app_client, db_session):
    _roles(map_1__user_1="owner", map_1__user_2="member")
    pin = _insert_pin(db_session, created_by="user_1")
    assert _restore(app_client, pin, "user_2").status_code == 404     # 복구할 수 있는 핀이 아니다 — 존재를 알리지 않는다


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


# ── Codex 검수(#1193): live↔db 중복 양방향, 실제 확정 리스트 복원 ──

def test_live_pin_restore_is_409_when_a_db_pin_took_the_same_place_meanwhile(app_client, db_session):
    from pins.tests.test_pins_api import KALGUKSU
    live = app_client.post("/maps/map_1/pins", cookies=_auth(), json={
        "source": "live", "category": "음식점", "kakao_place_id": "kakao:1001", "search_query": "성수 칼국수"}).json()
    assert app_client.delete(f"/pins/{live['id']}", cookies=_auth()).status_code == 204
    db_pin = app_client.post("/maps/map_1/pins", cookies=_auth(), json=KALGUKSU)    # 같은 카카오 ID가 자체 DB 장소에 기록된다
    assert db_pin.status_code == 201
    res = app_client.post(f"/pins/{live['id']}/restore", cookies=_auth())
    assert res.status_code == 409 and res.json()["detail"]["pin_id"] == db_pin.json()["id"]
    db_session.expire_all()
    assert db_session.get(PinRow, __import__("uuid").UUID(live["id"])).deleted_at is not None


def _confirmed_then_deleted(app_client, db_session):
    from datetime import datetime, timedelta, timezone

    from shortlist.models import ShortlistItem
    past = datetime.now(timezone.utc) - timedelta(days=1)
    first, second = _insert_pin(db_session, kind="확정"), _insert_pin(db_session, kind="확정")
    db_session.add_all([ShortlistItem(map_id="map_1", pin_id=first.id, added_by="user_1", visit_order=0, added_at=past),
                        ShortlistItem(map_id="map_1", pin_id=second.id, added_by="user_1", visit_order=1, added_at=past)])
    db_session.commit()
    assert app_client.delete(f"/pins/{first.id}", cookies=_auth()).status_code == 204   # 실제 삭제 경로가 확정 항목을 정리한다
    db_session.expire_all()
    assert db_session.get(PinRow, first.id).deleted_was_confirmed is True
    return first, second


def test_confirmed_pin_returns_to_the_end_of_the_real_shortlist_with_confirmed_kind_in_the_event(app_client, db_session):
    from pins.tests.test_pins_api import _events
    first, second = _confirmed_then_deleted(app_client, db_session)
    res = _restore(app_client, first)
    assert res.status_code == 200 and res.json()["kind"] == "확정"
    items = app_client.get("/maps/map_1/shortlist", cookies=_auth()).json()
    assert [i["pin"]["id"] for i in items] == [str(second.id), str(first.id)]            # 맨 뒤
    event = _events(db_session, type="pin.restored")[-1]
    assert event.payload["id"] == str(first.id) and event.payload["kind"] == "확정"


def test_shortlist_failure_rolls_the_restore_back(app_client, db_session, monkeypatch):
    import pytest
    first, _ = _confirmed_then_deleted(app_client, db_session)

    def boom(db, *, pin_id):
        raise RuntimeError("shortlist down")

    monkeypatch.setattr("shortlist.api.restore_confirmed", boom)
    with pytest.raises(RuntimeError):
        _restore(app_client, first)
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(PinRow, first.id).deleted_at is not None

"""api.restore_confirmed(#1013) — 삭제 때 확정이었던 핀을 확정 리스트 맨 뒤로 되올린다."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from common.errors import AppError
from pins.models import Pin
from shortlist import api, service
from shortlist.models import ShortlistItem

# 테스트 트랜잭션 안에서는 now()가 늘 같아서, 이미 있던 항목은 과거 시각으로 둔다(실제로는 복구가 나중 트랜잭션이다)
_PAST = datetime.now(timezone.utc) - timedelta(days=1)


def _pin(db, map_id, *, kind="일반", created_by="u1", deleted=False):
    pin = Pin(
        map_id=map_id, category="음식점", kind=kind, origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}_{created_by}_{kind}_{uuid.uuid4().hex}", search_query="맛집", visibility="public",
        created_by=created_by,
    )
    db.add(pin)
    db.flush()
    return pin


def _confirm(db, map_id, pin, order=None):
    db.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by="u1", visit_order=order, added_at=_PAST))
    db.flush()


def test_restores_to_end_and_marks_kind(db_session):
    first, second = _pin(db_session, "m1", kind="확정"), _pin(db_session, "m1", kind="확정")
    _confirm(db_session, "m1", first, order=0)
    _confirm(db_session, "m1", second, order=1)
    back = _pin(db_session, "m1", created_by="u2")

    assert api.restore_confirmed(db_session, pin_id=str(back.id)) is True

    assert [i.pin_id for i in service.list_items(db_session, map_id="m1")] == [first.id, second.id, back.id]
    db_session.refresh(back)
    assert back.kind == "확정"
    assert db_session.query(ShortlistItem).filter_by(pin_id=back.id).one().added_by == "u2"
    assert db_session.query(ShortlistItem).filter_by(pin_id=back.id).one().scheduled_date is None


def test_idempotent(db_session):
    pin = _pin(db_session, "m1")
    api.restore_confirmed(db_session, pin_id=str(pin.id))

    assert api.restore_confirmed(db_session, pin_id=str(pin.id)) is False
    assert db_session.query(ShortlistItem).count() == 1


def test_other_maps_untouched(db_session):
    other = _pin(db_session, "m2", kind="확정")
    _confirm(db_session, "m2", other)
    pin = _pin(db_session, "m1")

    api.restore_confirmed(db_session, pin_id=str(pin.id))

    assert [i.pin_id for i in service.list_items(db_session, map_id="m2")] == [other.id]
    assert [i.pin_id for i in service.list_items(db_session, map_id="m1")] == [pin.id]


def test_many_items_have_no_limit(db_session):
    for _ in range(30):
        _confirm(db_session, "m1", _pin(db_session, "m1", kind="확정"))
    pin = _pin(db_session, "m1")

    assert api.restore_confirmed(db_session, pin_id=str(pin.id)) is True
    assert service.list_items(db_session, map_id="m1")[-1].pin_id == pin.id


def test_missing_pin_is_404(db_session):
    with pytest.raises(AppError):
        api.restore_confirmed(db_session, pin_id="00000000-0000-0000-0000-000000000000")


def test_restored_item_uses_clock_timestamp_not_transaction_start(db_session):
    # 기본값 now()(트랜잭션 시작 시각)로 만든 항목보다 복구 항목의 added_at이 뒤다 — 잠금 대기 중 다른 추가가 끼어도 맨 뒤
    existing = _pin(db_session, "m1", kind="확정")
    db_session.add(ShortlistItem(map_id="m1", pin_id=existing.id, added_by="u1"))
    back = _pin(db_session, "m1")
    db_session.flush()

    api.restore_confirmed(db_session, pin_id=str(back.id))

    added = {i.pin_id: i.added_at for i in db_session.query(ShortlistItem).all()}
    assert added[back.id] > added[existing.id]
    assert service.list_items(db_session, map_id="m1")[-1].pin_id == back.id

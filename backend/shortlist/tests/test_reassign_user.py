"""api.reassign_user(#560) — 게스트가 추가한 확정 항목의 added_by만 옮긴다."""

from pins.models import Pin
from shortlist import api
from shortlist.models import ShortlistItem


def _item(db, map_id, added_by, order=None):
    pin = Pin(
        map_id=map_id, category="음식점", kind="확정", origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}_{added_by}", search_query="맛집", visibility="public", created_by=added_by,
    )
    db.add(pin)
    db.flush()
    db.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by=added_by, visit_order=order))
    db.flush()
    return pin.id


def _added_by(db):
    return {i.pin_id: i.added_by for i in db.query(ShortlistItem).all()}


def test_moves_items_across_maps_keeping_pin_and_order(db_session):
    p1 = _item(db_session, "m1", "guest", order=2)
    p2 = _item(db_session, "m2", "guest", order=1)

    result = api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert result == {"shortlist_items": 2}
    assert _added_by(db_session) == {p1: "kakao", p2: "kakao"}
    assert {i.pin_id: i.visit_order for i in db_session.query(ShortlistItem).all()} == {p1: 2, p2: 1}


def test_idempotent(db_session):
    _item(db_session, "m1", "guest")
    api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao") == {"shortlist_items": 0}


def test_other_users_items_unchanged(db_session):
    mine = _item(db_session, "m1", "guest")
    other = _item(db_session, "m1", "someone")

    api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert _added_by(db_session) == {mine: "kakao", other: "someone"}


def test_same_id_is_noop(db_session):
    pin = _item(db_session, "m1", "u1")

    assert api.reassign_user(db_session, from_user_id="u1", to_user_id="u1") == {"shortlist_items": 0}
    assert _added_by(db_session) == {pin: "u1"}

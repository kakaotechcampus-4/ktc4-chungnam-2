"""api.reassign_user(#560) — 게스트 합치기가 부른다. 핀 작성자·반응을 옮기고 같은 핀 반응은 카카오 쪽이 이긴다."""

from pins import api
from pins.models import Pin, Reaction

GUEST, KAKAO, OTHER = "guest_1", "kakao_1", "other_1"


def _pin(db, key, created_by):
    pin = Pin(
        map_id="m1", category="음식점", kind="일반", origin="direct", source="live",
        kakao_place_id=f"kakao_{key}", search_query="맛집", visibility="public", created_by=created_by,
    )
    db.add(pin)
    db.flush()
    return pin


def _react(db, pin, user_id, type_="like", reason=None):
    db.add(Reaction(pin_id=pin.id, user_id=user_id, type=type_, reason_text=reason))
    db.flush()


def _reactions(db, pin):
    return {r.user_id: r.type for r in db.query(Reaction).filter(Reaction.pin_id == pin.id)}


def test_moves_pin_author(db_session):
    mine, other = _pin(db_session, "a", GUEST), _pin(db_session, "b", OTHER)

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    db_session.refresh(mine)
    db_session.refresh(other)
    assert result["pins"] == 1
    assert (mine.created_by, other.created_by) == (KAKAO, OTHER)


def test_moves_reactions(db_session):
    pin = _pin(db_session, "a", OTHER)
    _react(db_session, pin, GUEST, "against", "너무 멀어요")
    _react(db_session, pin, OTHER)

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["reactions"] == 1
    assert _reactions(db_session, pin) == {KAKAO: "against", OTHER: "like"}


def test_same_pin_conflict_keeps_kakao_reaction(db_session):
    conflict, solo = _pin(db_session, "a", OTHER), _pin(db_session, "b", OTHER)
    _react(db_session, conflict, GUEST, "against", "싫어요")
    _react(db_session, conflict, KAKAO, "like")
    _react(db_session, solo, GUEST)

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["reactions"] == 1
    assert _reactions(db_session, conflict) == {KAKAO: "like"}
    assert _reactions(db_session, solo) == {KAKAO: "like"}


def test_idempotent(db_session):
    pin = _pin(db_session, "a", GUEST)
    _react(db_session, pin, GUEST)

    api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)
    again = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert again == {"pins": 0, "reactions": 0}
    assert _reactions(db_session, pin) == {KAKAO: "like"}


def test_same_id_does_nothing(db_session):
    pin = _pin(db_session, "a", KAKAO)
    _react(db_session, pin, KAKAO)

    assert api.reassign_user(db_session, from_user_id=KAKAO, to_user_id=KAKAO) == {"pins": 0, "reactions": 0}
    assert _reactions(db_session, pin) == {KAKAO: "like"}

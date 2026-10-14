"""api.purge_map_data(#431) — 지도 정리가 부른다. 대상 지도의 반응·핀(소프트 삭제 포함)만 지우고 다른 지도는 안 건드린다."""

from datetime import datetime, timezone

from pins import api
from pins.models import Pin, Reaction


def _pin(db, map_id, key, *, deleted=False):
    pin = Pin(
        map_id=map_id, category="음식점", kind="일반", origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}_{key}", search_query="맛집", visibility="public", created_by="u1",
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(pin)
    db.flush()
    db.add(Reaction(pin_id=pin.id, user_id="u1", type="like"))
    db.add(Reaction(pin_id=pin.id, user_id="u2", type="against"))
    db.flush()
    return pin


def _counts(db):
    return {
        "pins": {p.map_id for p in db.query(Pin).all()},
        "reactions": db.query(Reaction).count(),
    }


def test_purge_deletes_only_target_maps_pins_and_reactions(db_session):
    _pin(db_session, "gone", "a")
    _pin(db_session, "gone", "b", deleted=True)
    _pin(db_session, "keep", "a")

    result = api.purge_map_data(db_session, map_ids=["gone"])

    assert result == {"reactions": 4, "pins": 2}
    assert _counts(db_session) == {"pins": {"keep"}, "reactions": 2}


def test_purge_handles_several_maps_and_ignores_unknown_ids(db_session):
    _pin(db_session, "gone1", "a")
    _pin(db_session, "gone2", "a")
    _pin(db_session, "keep", "a")

    result = api.purge_map_data(db_session, map_ids=["gone1", "gone2", "never_existed"])

    assert result == {"reactions": 4, "pins": 2}
    assert _counts(db_session)["pins"] == {"keep"}


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    _pin(db_session, "keep", "a")

    assert api.purge_map_data(db_session, map_ids=[]) == {"reactions": 0, "pins": 0}
    assert _counts(db_session) == {"pins": {"keep"}, "reactions": 2}

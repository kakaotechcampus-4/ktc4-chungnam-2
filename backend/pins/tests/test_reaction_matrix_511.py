"""#511 — pins.api.list_reaction_matrix: agent(v2) get_reaction_matrix의 원자료(docs/agent-v2.md 6.3·6.4·10절).
실제 PostgreSQL이 필요하다(conftest.py). 핀·반응은 DB에 직접 넣는다 — 이 함수는 읽기만 한다."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func

from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _db_pin(db_session, *, map_id="map_1", category="음식점", created_by="user_1", minutes=0, deleted=False,
            visibility="public"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}", geom=func.ST_SetSRID(func.ST_MakePoint(127.05, 37.54), 4326),
        visibility=visibility, created_by=created_by, created_at=T0 + timedelta(minutes=minutes),
        deleted_at=T0 + timedelta(hours=1) if deleted else None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _live_pin(db_session, *, map_id="map_1", category="음식점", created_by="user_2", minutes=0):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct", source="live",
        place_id=None, geom=None, kakao_place_id=f"kakao:{uuid.uuid4().hex[:6]}", search_query="성수 곱창",
        visibility="public", created_by=created_by, created_at=T0 + timedelta(minutes=minutes),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _react(db_session, pin, user_id, type_="like", *, minutes=0):
    row = ReactionRow(
        id=uuid.uuid4(), pin_id=pin.id, user_id=user_id, type=type_,
        reason_text="별로예요" if type_ == "against" else None,
        updated_at=T0 + timedelta(minutes=minutes),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _pin_ids(matrix):
    return [entry["pin_id"] for entry in matrix]


def test_returns_pin_fields_and_reactions(db_session):
    pin = _db_pin(db_session, created_by="user_1")
    like = _react(db_session, pin, "user_2", "like", minutes=5)
    against = _react(db_session, pin, "user_3", "against", minutes=10)

    assert pins_api.list_reaction_matrix(db_session, map_id="map_1") == [{
        "pin_id": str(pin.id), "category": "음식점", "source": "db", "place_id": pin.place_id,
        "search_query": None, "created_by": "user_1", "created_at": T0,
        "reactions": [
            {"reaction_id": str(like.id), "user_id": "user_2", "type": "like", "updated_at": T0 + timedelta(minutes=5)},
            {"reaction_id": str(against.id), "user_id": "user_3", "type": "against",
             "updated_at": T0 + timedelta(minutes=10)},
        ],
    }]


def test_pin_without_reactions_is_included_with_empty_list(db_session):
    reacted = _db_pin(db_session, minutes=0)
    silent = _db_pin(db_session, minutes=1)
    _react(db_session, reacted, "user_2")

    matrix = pins_api.list_reaction_matrix(db_session, map_id="map_1")

    assert _pin_ids(matrix) == [str(reacted.id), str(silent.id)]
    assert matrix[1]["reactions"] == []


def test_soft_deleted_pin_is_excluded(db_session):
    alive = _db_pin(db_session)
    deleted = _db_pin(db_session, minutes=1, deleted=True)
    _react(db_session, deleted, "user_2")

    assert _pin_ids(pins_api.list_reaction_matrix(db_session, map_id="map_1")) == [str(alive.id)]


def test_other_map_is_excluded(db_session):
    mine = _db_pin(db_session, map_id="map_1")
    other = _db_pin(db_session, map_id="map_2", minutes=1)
    _react(db_session, other, "user_2")

    assert _pin_ids(pins_api.list_reaction_matrix(db_session, map_id="map_1")) == [str(mine.id)]


def test_category_filter_and_none_means_all(db_session):
    food = _db_pin(db_session, category="음식점", minutes=0)
    cafe = _db_pin(db_session, category="카페", minutes=1)

    assert _pin_ids(pins_api.list_reaction_matrix(db_session, map_id="map_1", category="카페")) == [str(cafe.id)]
    assert _pin_ids(pins_api.list_reaction_matrix(db_session, map_id="map_1")) == [str(food.id), str(cafe.id)]


def test_live_pin_without_place_id_is_included(db_session):
    live = _live_pin(db_session)
    _react(db_session, live, "user_1", "against")

    [entry] = pins_api.list_reaction_matrix(db_session, map_id="map_1")

    assert entry["pin_id"] == str(live.id)
    assert entry["source"] == "live" and entry["place_id"] is None and entry["search_query"] == "성수 곱창"
    assert [r["type"] for r in entry["reactions"]] == ["against"]


def test_private_pin_is_excluded(db_session):
    public = _db_pin(db_session)
    _db_pin(db_session, minutes=1, visibility="private")

    assert _pin_ids(pins_api.list_reaction_matrix(db_session, map_id="map_1")) == [str(public.id)]


def test_reads_pins_and_reactions_in_one_query(db_session):
    for minutes in range(3):
        pin = _db_pin(db_session, minutes=minutes)
        _react(db_session, pin, "user_2")
        _react(db_session, pin, "user_3", "against")

    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        matrix = pins_api.list_reaction_matrix(db_session, map_id="map_1")
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(matrix) == 3 and all(len(entry["reactions"]) == 2 for entry in matrix)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1

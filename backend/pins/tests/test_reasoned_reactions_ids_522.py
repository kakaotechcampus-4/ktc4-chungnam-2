"""#522 — list_reasoned_reactions의 각 항목에 reaction_id·updated_at을 더했다. 기존 키는 그대로다(recommend 호출부)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _pin(db_session):
    row = PinRow(
        id=uuid.uuid4(), map_id="map_1", category="음식점", kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}", geom=func.ST_SetSRID(func.ST_MakePoint(127.05, 37.54), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_each_item_carries_reaction_id_and_updated_at(db_session):
    pin = _pin(db_session)
    reaction = ReactionRow(id=uuid.uuid4(), pin_id=pin.id, user_id="user_2", type="against",
                           reason_text="너무 시끄러워요", updated_at=T0)
    db_session.add(reaction)
    db_session.flush()

    [item] = pins_api.list_reasoned_reactions(db_session, map_id="map_1", category="음식점")

    assert item["reaction_id"] == str(reaction.id)
    assert item["updated_at"] == T0


def test_existing_keys_are_unchanged(db_session):
    pin = _pin(db_session)
    db_session.add(ReactionRow(pin_id=pin.id, user_id="user_2", type="like", reason_text="분위기 좋아요"))
    db_session.flush()

    [item] = pins_api.list_reasoned_reactions(db_session, map_id="map_1", category="음식점")

    assert set(item) == {
        "pin_id", "user_id", "type", "reason_text", "reason_chip_ids", "chips",   # recommend가 읽는 키
        "reaction_id", "updated_at",                                               # #522로 더한 키
    }
    assert (item["pin_id"], item["user_id"], item["type"], item["reason_text"]) == (
        str(pin.id), "user_2", "like", "분위기 좋아요",
    )

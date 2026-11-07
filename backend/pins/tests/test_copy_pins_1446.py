"""api.copy_pins_to_map(#1446) — 지도 복사가 부른다. 살아 있는 공개 핀만 일반 핀으로 옮기고, 찍은 사람은 복사한 사람이다."""

from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select

from pins import api
from pins.models import Pin, Reaction


def _pin(db, map_id, **fields):
    values = dict(
        map_id=map_id, category="음식점", kind="일반", origin="direct", source="db", place_id="p1",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.16, 35.16), 4326), visibility="public", created_by="u1",
    )
    values.update(fields)
    pin = Pin(**values)
    db.add(pin)
    db.flush()
    return pin


def test_copies_live_public_pins_as_plain_pins_of_the_copier(db_session):
    db_pin = _pin(db_session, "src", memo="꼭 가자")
    db_session.add(Reaction(pin_id=db_pin.id, user_id="u2", type="like"))
    _pin(db_session, "src", place_id="p2", kind="확정", origin="ai", checks=[], reason="조용함",
         member_fulfillment={"satisfied": 2, "total": 3}, place_source={"provider": "own"})
    _pin(db_session, "src", source="live", place_id=None, geom=None, kakao_place_id="kakao:9", search_query="곱창",
         category="카페")
    _pin(db_session, "src", place_id="gone", deleted_at=datetime.now(timezone.utc), deleted_by="u1")   # 휴지통
    _pin(db_session, "src", place_id="secret", visibility="private")
    _pin(db_session, "other", place_id="p9")

    assert api.copy_pins_to_map(db_session, from_map_id="src", to_map_id="dst", created_by="me") == 3

    copied = db_session.execute(select(Pin).where(Pin.map_id == "dst").order_by(Pin.place_id)).scalars().all()
    assert [(p.place_id, p.kakao_place_id, p.search_query, p.category, p.source) for p in copied] == [
        ("p1", None, None, "음식점", "db"), ("p2", None, None, "음식점", "db"), (None, "kakao:9", "곱창", "카페", "live"),
    ]
    assert {(p.kind, p.origin, p.visibility, p.created_by) for p in copied} == {("일반", "direct", "public", "me")}
    assert [p.memo for p in copied] == ["꼭 가자", None, None]
    assert all(p.checks is None and p.reason is None and p.member_fulfillment is None and p.place_source is None for p in copied)
    assert all(p.deleted_at is None for p in copied)
    assert len({p.id for p in copied} | {db_pin.id}) == 4                       # 새 id
    point = cast(Pin.geom, Geometry())
    lat_lng = db_session.execute(
        select(func.ST_Y(point), func.ST_X(point)).where(Pin.map_id == "dst", Pin.place_id == "p1")
    ).one()
    assert tuple(lat_lng) == (35.16, 129.16)
    assert db_session.execute(select(func.count()).select_from(Reaction).where(Reaction.pin_id.in_([p.id for p in copied]))).scalar_one() == 0


def test_copying_a_map_without_pins_makes_nothing(db_session):
    assert api.copy_pins_to_map(db_session, from_map_id="empty", to_map_id="dst", created_by="me") == 0

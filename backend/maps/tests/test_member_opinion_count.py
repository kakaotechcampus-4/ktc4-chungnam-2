"""Member.opinion_count(#1562) — 구성원 목록이 pins.api 집계 한 번으로 채운다."""

import uuid

from sqlalchemy import func

from maps.tests.test_delete_leave_api import _auth, _create_map, _join
from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow


def _pin_with_reaction(db_session, map_id, reactor, *, deleted=False):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct", place_id=f"p-{uuid.uuid4()}",
        geom=func.ST_SetSRID(func.ST_MakePoint(126.9, 37.5), 4326), visibility="public", created_by="user_1",
    )
    db_session.add(row)
    db_session.flush()
    db_session.add(ReactionRow(pin_id=row.id, user_id=reactor, type="like"))
    if deleted:
        row.deleted_at = func.now()
    db_session.commit()


def test_members_carry_opinion_count_from_one_pins_aggregate(app_client, db_session, monkeypatch):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _pin_with_reaction(db_session, map_id, "user_2")
    _pin_with_reaction(db_session, map_id, "user_2")
    _pin_with_reaction(db_session, map_id, "user_2", deleted=True)   # 지운 핀의 반응은 세지 않는다
    calls = []
    real = pins_api.count_reactions_by_user
    monkeypatch.setattr(pins_api, "count_reactions_by_user", lambda db, **kw: calls.append(kw) or real(db, **kw))

    members = {m["user_id"]: m for m in app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1")).json()}
    assert members["user_2"]["opinion_count"] == 2
    assert members["user_1"]["opinion_count"] == 0   # 반응이 없는 사람은 키가 없는 집계라도 0
    assert calls == [{"map_id": map_id}]             # 구성원 수만큼 묻지 않는다

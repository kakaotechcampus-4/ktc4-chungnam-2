"""GET /maps/{mapId}/news(#1556) — 마지막으로 본 뒤 새 핀·새 의견. 무엇이 새것인지는 pins.api가 정하고 maps는 기준 시각과 이름을 채운다."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from maps.models import Membership as MembershipRow
from maps.tests.test_delete_leave_api import _auth, _create_map, _join
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow

# 테스트 세션은 긴 트랜잭션이라 DB now()가 한 시각에 멈춰 있다 — 「이전」과 「이후」는 시각을 직접 적어 가른다.
BEFORE = timedelta(hours=-1)
AFTER = timedelta(hours=1)


def _pin(db_session, map_id, created_by="user_1", when=AFTER):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct", place_id=f"p-{uuid.uuid4()}",
        geom=func.ST_SetSRID(func.ST_MakePoint(126.9, 37.5), 4326), visibility="public", created_by=created_by,
        created_at=datetime.now(timezone.utc) + when,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _react(db_session, pin_id, user_id, when=AFTER):
    at = datetime.now(timezone.utc) + when
    db_session.add(ReactionRow(pin_id=pin_id, user_id=user_id, type="against", reason_text="별로", created_at=at, updated_at=at))
    db_session.commit()


def _news(app_client, map_id, user_id="user_1"):
    return app_client.get(f"/maps/{map_id}/news", cookies=_auth(user_id))


def _seen(app_client, map_id, user_id):
    assert app_client.post(f"/maps/{map_id}/seen", cookies=_auth(user_id)).status_code == 204


def test_never_seen_map_has_null_since_and_empty_lists(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _pin(db_session, map_id, created_by="user_2")
    assert _news(app_client, map_id).json() == {
        "since": None, "new_pin_ids": [], "new_reactions": [], "truncated": False,
    }


def test_news_has_others_new_pins_and_reactions_only(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    old_pin = _pin(db_session, map_id, created_by="user_2", when=BEFORE)
    _seen(app_client, map_id, "user_1")
    new_pin = _pin(db_session, map_id, created_by="user_2")
    my_pin = _pin(db_session, map_id, created_by="user_1")   # 내가 찍은 핀은 새 소식이 아니다
    _react(db_session, old_pin, "user_2")                    # 옛 핀에 새로 남긴 남의 의견은 새 의견이다
    _react(db_session, my_pin, "user_1")                     # 내 의견은 아니다

    body = _news(app_client, map_id).json()
    assert body["new_pin_ids"] == [str(new_pin)]
    assert [(r["pin_id"], r["user_id"], r["display_name"], r["type"], r["reason_text"], r["reason_chip_ids"])
            for r in body["new_reactions"]] == [(str(old_pin), "user_2", "user_2", "against", "별로", [])]
    assert body["since"] and body["truncated"] is False


def test_reaction_without_reason_omits_reason_text_but_since_null_stays(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert "since" in _news(app_client, map_id).json()   # 처음 연 지도: since는 null로 남는다
    _seen(app_client, map_id, "user_1")
    pin = _pin(db_session, map_id, created_by="user_1")
    at = datetime.now(timezone.utc) + AFTER
    db_session.add(ReactionRow(pin_id=pin, user_id="user_2", type="like", created_at=at, updated_at=at))
    db_session.commit()
    [reaction] = _news(app_client, map_id).json()["new_reactions"]
    assert "reason_text" not in reaction and reaction["reason_chip_ids"] == []


def test_news_does_not_move_last_seen_and_is_per_person(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _seen(app_client, map_id, "user_1")
    first = db_session.execute(select(MembershipRow.last_seen_at).where(MembershipRow.user_id == "user_1")).scalar_one()
    _pin(db_session, map_id, created_by="user_2")
    assert len(_news(app_client, map_id).json()["new_pin_ids"]) == 1
    assert len(_news(app_client, map_id).json()["new_pin_ids"]) == 1   # 다시 불러도 그대로 — 읽기만 한다
    db_session.expire_all()
    assert db_session.execute(select(MembershipRow.last_seen_at).where(MembershipRow.user_id == "user_1")).scalar_one() == first
    assert _news(app_client, map_id, "user_2").json()["new_pin_ids"] == []   # 남이 찍은 핀이 아니라 user_2에게는 없다. 사람마다 다르다


def test_news_non_member_404_anonymous_401(app_client):
    map_id = _create_map(app_client)
    assert _news(app_client, map_id, "outsider").status_code == 404
    assert app_client.get(f"/maps/{map_id}/news").status_code == 401


def test_news_over_limit_is_truncated(app_client, db_session, monkeypatch):
    monkeypatch.setattr("maps.service.NEWS_LIMIT", 2)
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _seen(app_client, map_id, "user_1")
    for _ in range(3):
        _pin(db_session, map_id, created_by="user_2")
    body = _news(app_client, map_id).json()
    assert len(body["new_pin_ids"]) == 2 and body["truncated"] is True

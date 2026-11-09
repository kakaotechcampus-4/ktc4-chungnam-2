"""#1562·#1556 — maps가 쓰는 pins.api 함수: 구성원별 의견 수, 새 소식."""

from datetime import datetime, timedelta, timezone

import pytest

from pins import api as pins_api
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import _auth, _insert_pin

NOW = datetime.now(timezone.utc)


def _react(db, pin, user, type_="like", *, updated_at=None, text=None, chips=None):
    row = ReactionRow(pin_id=pin.id, user_id=user, type=type_, reason_text=text, reason_chip_ids=chips)
    db.add(row)
    db.flush()
    if updated_at is not None:
        row.updated_at = updated_at
    db.commit()
    return row


def _pin_at(db, created_at, **kw):
    pin = _insert_pin(db, **kw)
    pin.created_at = created_at
    db.commit()
    return pin


# ── 구성원별 의견 수(#1562) ──

def test_counts_per_user_skip_deleted_pins_and_other_maps(db_session):
    a, b, gone, other = _insert_pin(db_session), _insert_pin(db_session), _insert_pin(db_session, deleted=True), _insert_pin(db_session, map_id="map_2")
    _react(db_session, a, "u1"); _react(db_session, b, "u1", "against", text="별로"); _react(db_session, a, "u2")
    _react(db_session, gone, "u3"); _react(db_session, other, "u1")
    assert pins_api.count_reactions_by_user(db_session, map_id="map_1") == {"u1": 2, "u2": 1}
    assert pins_api.count_reactions_by_user(db_session, map_id="map_empty") == {}


def test_members_with_opinion_is_the_number_of_users_with_a_count(app_client, db_session):
    """FilterCounts.members_with_opinion과 같은 기준 — 한 곳에서 나온다."""
    a, gone = _insert_pin(db_session), _insert_pin(db_session, deleted=True)
    _react(db_session, a, "user_1"); _react(db_session, a, "user_2"); _react(db_session, gone, "user_3")
    counts = pins_api.count_reactions_by_user(db_session, map_id="map_1")
    body = app_client.get("/maps/map_1/counts", cookies=_auth()).json()
    assert body["members_with_opinion"] == len([u for u, n in counts.items() if n >= 1]) == 2


# ── 새 소식(#1556) ──

def _news(db, since, *, limit=100):
    return pins_api.list_new_since(db, map_id="map_1", since=since, exclude_user_id="viewer", limit=limit)


def test_news_new_pins_exclude_mine_old_deleted_and_restored_and_sort_recent_first(db_session):
    since = NOW - timedelta(hours=2)
    old = _pin_at(db_session, since - timedelta(minutes=1), created_by="u2")
    first = _pin_at(db_session, since + timedelta(minutes=10), created_by="u2")
    mine = _pin_at(db_session, since + timedelta(minutes=20), created_by="viewer")
    last = _pin_at(db_session, since + timedelta(minutes=30), created_by="u3")
    gone = _pin_at(db_session, since + timedelta(minutes=40), created_by="u2")
    gone.deleted_at = NOW
    db_session.commit()
    news = _news(db_session, since)
    assert news[0] == [str(last.id), str(first.id)]
    assert not news[2]


def test_news_new_reactions_use_updated_at_exclude_mine_and_deleted_pins(db_session):
    since = NOW - timedelta(hours=2)
    pin = _insert_pin(db_session)
    gone = _insert_pin(db_session, deleted=True)
    _react(db_session, pin, "u2", "against", updated_at=since + timedelta(minutes=5), text="멀어요", chips=["far"])
    _react(db_session, pin, "u3", "like", updated_at=since + timedelta(minutes=15))
    _react(db_session, pin, "viewer", "like", updated_at=since + timedelta(minutes=20))   # 내 것
    _react(db_session, pin, "u4", "like", updated_at=since - timedelta(minutes=1))        # since 전
    _react(db_session, gone, "u5", "like", updated_at=since + timedelta(minutes=9))        # 지운 핀
    reactions = _news(db_session, since)[1]
    assert [r["user_id"] for r in reactions] == ["u3", "u2"]
    assert reactions[1] == {"pin_id": str(pin.id), "user_id": "u2", "type": "against", "reason_text": "멀어요",
                            "reason_chip_ids": ["far"], "updated_at": since + timedelta(minutes=5)}
    assert reactions[0]["reason_text"] is None and reactions[0]["reason_chip_ids"] == []


def test_news_is_cut_at_the_limit_and_marks_truncated(db_session):
    since = NOW - timedelta(hours=2)
    pins = [_pin_at(db_session, since + timedelta(minutes=i + 1), created_by="u2") for i in range(3)]
    news = _news(db_session, since, limit=2)
    assert news[0] == [str(pins[2].id), str(pins[1].id)] and news[2]
    exact = _news(db_session, since + timedelta(minutes=1), limit=2)
    assert exact[0] == [str(pins[2].id), str(pins[1].id)] and not exact[2]


def test_news_rejects_naive_since_and_is_per_map(db_session):
    _pin_at(db_session, NOW, created_by="u2", map_id="map_2")
    with pytest.raises(ValueError):
        pins_api.list_new_since(db_session, map_id="map_1", since=datetime(2026, 1, 1), exclude_user_id="v", limit=100)
    assert _news(db_session, NOW - timedelta(days=1))[0] == []

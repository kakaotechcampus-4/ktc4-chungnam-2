"""#312 — Pin.created_at · counts 구성원 수 · reaction.changed 작성자 · 칩 API·검증 · count_public_pins_by_map."""

from datetime import datetime, timezone

import pytest

from auth.models import User
from auth.testing import ensure_users
from pins import api as pins_api
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth, _events, _insert_pin


def _react(app_client, pin, user, body):
    return app_client.put(f"/pins/{pin.id}/reaction", json=body, cookies=_auth(user))


# ---- 1. Pin.created_at ----

def test_pin_created_at_is_filled_on_create_and_list(app_client):
    created = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    assert created["created_at"]
    listed = app_client.get("/maps/map_1/pins", cookies=_auth()).json()
    assert listed[0]["created_at"] == created["created_at"]


def test_pin_created_event_payload_carries_json_created_at(app_client, db_session):
    app_client.post("/maps/map_1/pins", json=CAFE, cookies=_auth())
    (event,) = _events(db_session, type="pin.created")
    assert isinstance(event.payload["created_at"], str)


# ---- 2. counts ----

def test_counts_members_with_opinion_counts_distinct_current_members(app_client, db_session, monkeypatch):
    monkeypatch.setattr("pins.router.maps_api.count_members", lambda db, map_id: 4)
    pin_a = _insert_pin(db_session, place_id="m_a")
    pin_b = _insert_pin(db_session, place_id="m_b")
    _react(app_client, pin_a, "user_1", {"type": "like"})
    _react(app_client, pin_b, "user_1", {"type": "neutral"})   # 같은 사람이 두 핀에 — 한 명
    _react(app_client, pin_a, "user_2", {"type": "against", "reason_text": "멀어요"})

    body = app_client.get("/maps/map_1/counts", cookies=_auth()).json()
    assert body["members_with_opinion"] == 2
    assert body["members_total"] == 4


def test_counts_members_with_opinion_ignores_deleted_pins_and_withdrawn_users(app_client, db_session):
    gone = _insert_pin(db_session, place_id="m_gone")
    alive = _insert_pin(db_session, place_id="m_alive")
    _react(app_client, gone, "user_1", {"type": "like"})          # 삭제된 핀의 반응
    _react(app_client, alive, "stranger", {"type": "like"})       # 탈퇴자의 반응
    _react(app_client, alive, "user_2", {"type": "like"})
    app_client.delete(f"/pins/{gone.id}", cookies=_auth())
    ensure_users(db_session, "stranger")
    db_session.query(User).filter(User.id == "stranger").update({"deleted_at": datetime.now(timezone.utc)})
    db_session.commit()

    assert app_client.get("/maps/map_1/counts", cookies=_auth()).json()["members_with_opinion"] == 1


# ---- 3. reaction.changed ----

def test_reaction_changed_event_names_the_reactor_and_never_carries_reasons(app_client, db_session):
    ensure_users(db_session, "user_2", display_names={"user_2": "지우"})
    db_session.commit()
    pin = _insert_pin(db_session, place_id="ev_who")
    _react(app_client, pin, "user_2", {"type": "against", "reason_text": "비밀 사유", "reason_chip_ids": ["food_spicy"]})
    app_client.delete(f"/pins/{pin.id}/reaction", cookies=_auth("user_2"))

    put_event, delete_event = _events(db_session, type="reaction.changed")
    assert (put_event.payload["user_id"], put_event.payload["display_name"], put_event.payload["type"]) == (
        "user_2", "지우", "against",
    )
    assert delete_event.payload["type"] is None and delete_event.payload["user_id"] == "user_2"
    for event in (put_event, delete_event):
        assert not {"reason_text", "reason_chip_ids", "my_reaction"} & set(event.payload)
        assert "비밀 사유" not in str(event.payload)


# ---- 4. GET /categories/{category}/reason-chips ----

def test_reason_chips_endpoint_returns_category_then_common(app_client):
    resp = app_client.get("/categories/관광지/reason-chips", cookies=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert [c["id"] for c in body] == [
        "sight_inaccessible", "sight_expensive", "sight_noisy", "common_not_my_taste", "common_far",
    ]
    assert body[0] == {"id": "sight_inaccessible", "label": "휠체어·유모차로 가기 힘들어요", "fact_key": "accessible"}
    assert body[-1] == {"id": "common_far", "label": "너무 멀어요"}   # fact_key 생략


@pytest.mark.parametrize("category", ["숙소", "기타"])
def test_reason_chips_for_non_reactable_category_is_empty(app_client, category):
    assert app_client.get(f"/categories/{category}/reason-chips", cookies=_auth()).json() == []


def test_reason_chips_needs_login_but_not_membership(app_client):
    assert app_client.get("/categories/음식점/reason-chips", cookies=_auth("outsider")).status_code == 200   # 구성원 아님
    app_client.cookies.clear()
    assert app_client.get("/categories/음식점/reason-chips").status_code == 401


def test_reason_chips_unknown_category_is_422(app_client):
    assert app_client.get("/categories/없는분류/reason-chips", cookies=_auth()).status_code == 422


# ---- 5. 칩 id 검증 ----

@pytest.mark.parametrize("chip_id", ["cafe_noisy", "매워요", "unknown"])
def test_reaction_rejects_chip_not_in_the_pins_category(app_client, db_session, chip_id):
    pin = _insert_pin(db_session, category="음식점", place_id="chip_bad")
    resp = _react(app_client, pin, "user_2", {"type": "against", "reason_chip_ids": ["food_spicy", chip_id]})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert resp.json()["detail"]["reason_chip_id"] == chip_id


def test_reaction_accepts_category_and_common_chips(app_client, db_session):
    pin = _insert_pin(db_session, category="음식점", place_id="chip_ok")
    resp = _react(app_client, pin, "user_2", {"type": "against", "reason_chip_ids": ["food_spicy", "common_far"]})
    assert resp.status_code == 200
    assert resp.json()["reason_chip_ids"] == ["food_spicy", "common_far"]


def test_chip_only_against_enters_evidence_as_label_sentence_and_legacy_values_survive(db_session):
    pin = _insert_pin(db_session, place_id="chip_ev")
    legacy = _insert_pin(db_session, place_id="chip_legacy")
    db_session.add_all([
        ReactionRow(pin_id=pin.id, user_id="user_2", type="against", reason_chip_ids=["food_spicy", "common_far"]),
        ReactionRow(pin_id=legacy.id, user_id="user_2", type="against", reason_chip_ids=["매워요"]),   # 옛 값
    ])
    db_session.commit()

    rows = {r["pin_id"]: r for r in pins_api.list_reasoned_reactions(db_session, map_id="map_1", category="음식점")}
    assert rows[str(pin.id)]["reason_text"] == "매워요, 너무 멀어요"
    assert rows[str(legacy.id)]["reason_text"] == "매워요"


# ---- count_public_pins_by_map (#313이 쓴다) ----

def test_count_public_pins_by_map(db_session):
    _insert_pin(db_session, place_id="cp1")
    _insert_pin(db_session, place_id="cp2", created_by="user_2")
    _insert_pin(db_session, place_id="cp3", deleted=True)
    _insert_pin(db_session, place_id="cp4", visibility="private", kind="AI추천")
    _insert_pin(db_session, place_id="cp5", map_id="map_other")

    assert pins_api.count_public_pins_by_map(db_session, ["map_1", "map_other", "map_empty"]) == {
        "map_1": 2, "map_other": 1, "map_empty": 0,
    }
    assert pins_api.count_public_pins_by_map(db_session, []) == {}

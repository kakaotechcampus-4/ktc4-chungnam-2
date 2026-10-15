"""#466 — PATCH /pins/{pinId}: 핀 메모·분류 수정. 찍은 사람만(pin.edit), AI 추천·확정 핀은 403(can_edit=false).

분류는 live 핀만, 음식점·카페·관광지만, 반응이 없을 때만 바꾼다. 수정과 pin.updated 이벤트는 같은 트랜잭션이다.
"""

import pytest
from sqlalchemy import select

from authz.core import Principal, Resource
from common import categories
from common.errors import AppError
from pins import core
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.schemas import PinUpdateRequest
from pins.tests.test_pins_api import KALGUKSU, _auth, _events, _insert_pin

LIVE = {
    "source": "live", "category": "음식점", "kakao_place_id": "kakao:9001",
    "search_query": "성수 곱창", "memo": "여기 곱창 맛있대",
}


def _live(app_client, user="user_1", **overrides):
    resp = app_client.post("/maps/map_1/pins", json={**LIVE, **overrides}, cookies=_auth(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch(app_client, pin_id, body, user="user_1"):
    return app_client.patch(f"/pins/{pin_id}", json=body, cookies=_auth(user))


# ---- 메모 ----

def test_author_edits_memo_and_response_is_the_updated_pin(app_client):
    pin = _live(app_client)
    resp = _patch(app_client, pin["id"], {"memo": "웨이팅 길대"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["memo"] == "웨이팅 길대" and body["id"] == pin["id"]
    assert body["permissions"]["can_edit"] is True
    assert app_client.get("/maps/map_1/pins", cookies=_auth()).json()[0]["memo"] == "웨이팅 길대"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_memo_clears_it(app_client, db_session, blank):
    pin = _live(app_client)
    resp = _patch(app_client, pin["id"], {"memo": blank})
    assert resp.status_code == 200 and "memo" not in resp.json()
    assert db_session.execute(select(PinRow.memo).where(PinRow.kakao_place_id == "kakao:9001")).scalar_one() is None


def test_memo_can_be_edited_on_a_db_pin(app_client):
    pin = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    resp = _patch(app_client, pin["id"], {"memo": "점심에"})
    body = resp.json()
    assert resp.status_code == 200 and body["memo"] == "점심에"
    assert body["source"] == "db" and "lat" in body and "place_name" in body


def test_memo_over_200_chars_is_422(app_client):
    pin = _live(app_client)
    assert _patch(app_client, pin["id"], {"memo": "가" * 201}).status_code == 422
    assert _patch(app_client, pin["id"], {"memo": "가" * 200}).status_code == 200


@pytest.mark.parametrize("body", [
    {}, {"memo": None}, {"category": None}, {"place_id": "x"}, {"kind": "확정"},
    {"kakao_place_id": "kakao:1"}, {"search_query": "x"}, {"memo": "a", "lat": 1},
])
def test_empty_null_or_unknown_fields_are_422(app_client, body):
    pin = _live(app_client)
    resp = _patch(app_client, pin["id"], body)
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


# ---- 분류 ----

def test_author_changes_category_of_a_live_pin_without_reactions(app_client):
    pin = _live(app_client)
    resp = _patch(app_client, pin["id"], {"category": "카페"})
    assert resp.status_code == 200 and resp.json()["category"] == "카페"
    assert app_client.get("/maps/map_1/counts", cookies=_auth()).json()["by_category"]["카페"] == 1


def test_memo_and_category_can_change_together(app_client):
    pin = _live(app_client)
    body = _patch(app_client, pin["id"], {"memo": "카페였음", "category": "카페"}).json()
    assert (body["memo"], body["category"]) == ("카페였음", "카페")


@pytest.mark.parametrize("category", sorted(set(categories.all_categories()) - {"음식점", "카페", "관광지"}))
def test_live_category_must_be_pinnable(app_client, category):
    pin = _live(app_client)
    assert _patch(app_client, pin["id"], {"category": category}).status_code == 422


def test_category_of_a_db_pin_is_422_and_nothing_is_half_applied(app_client, db_session):
    pin = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    resp = _patch(app_client, pin["id"], {"category": "카페", "memo": "x"})
    assert resp.status_code == 422
    row = db_session.execute(select(PinRow).where(PinRow.id == pin["id"])).scalar_one()
    assert row.category == "음식점" and row.memo is None


def test_category_of_a_pin_with_any_reaction_is_422(app_client, db_session):
    pin = _live(app_client)
    assert app_client.put(f"/pins/{pin['id']}/reaction", json={"type": "like"}, cookies=_auth("user_2")).status_code == 200
    resp = _patch(app_client, pin["id"], {"category": "카페"})
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"
    assert _patch(app_client, pin["id"], {"memo": "메모는 가능"}).status_code == 200   # 메모는 반응과 무관
    assert db_session.execute(select(PinRow.category)).scalar_one() == "음식점"
    assert len(db_session.execute(select(ReactionRow)).scalars().all()) == 1


def test_category_is_editable_again_after_reactions_are_withdrawn(app_client):
    pin = _live(app_client)
    app_client.put(f"/pins/{pin['id']}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    app_client.delete(f"/pins/{pin['id']}/reaction", cookies=_auth("user_2"))
    assert _patch(app_client, pin["id"], {"category": "관광지"}).status_code == 200


# ---- 권한·상태 ----

def test_only_the_author_can_edit_and_others_see_can_edit_false(app_client, db_session):
    pin = _live(app_client)
    resp = _patch(app_client, pin["id"], {"memo": "남의 핀"}, user="user_2")
    assert resp.status_code == 403
    assert db_session.execute(select(PinRow.memo)).scalar_one() == LIVE["memo"]
    assert _events(db_session, type="pin.updated") == []
    assert app_client.get("/maps/map_1/pins", cookies=_auth("user_2")).json()[0]["permissions"]["can_edit"] is False
    assert app_client.get("/maps/map_1/pins", cookies=_auth("user_1")).json()[0]["permissions"]["can_edit"] is True


def test_non_member_gets_404_and_unknown_pin_404(app_client):
    pin = _live(app_client)
    assert _patch(app_client, pin["id"], {"memo": "x"}, user="outsider").status_code == 404
    assert _patch(app_client, "00000000-0000-0000-0000-000000000000", {"memo": "x"}).status_code == 404


def test_anonymous_gets_401(app_client):
    pin = _live(app_client)
    assert app_client.patch(f"/pins/{pin['id']}", json={"memo": "x"}).status_code == 401


@pytest.mark.parametrize("kind", ["AI추천", "확정"])
def test_ai_and_confirmed_pins_are_403_for_their_own_author_with_can_edit_false(app_client, db_session, kind):
    row = _insert_pin(db_session, kind=kind, created_by="user_1")
    shown = [p for p in app_client.get("/maps/map_1/pins", cookies=_auth()).json() if p["id"] == str(row.id)][0]
    assert shown["permissions"]["can_edit"] is False
    resp = _patch(app_client, str(row.id), {"memo": "고치기"})
    assert resp.status_code == 403 and resp.json()["code"] == "FORBIDDEN"
    db_session.refresh(row)
    assert row.memo is None
    assert _events(db_session, type="pin.updated") == []


def test_deleted_pin_is_404(app_client):
    pin = _live(app_client)
    app_client.delete(f"/pins/{pin['id']}", cookies=_auth())
    assert _patch(app_client, pin["id"], {"memo": "x"}).status_code == 404


# ---- 건드리지 않는 값 ----

def test_untouchable_columns_stay_the_same(app_client, db_session):
    check = {"fact_key": "k", "label": "l", "passed": True, "confidence": "known", "needs_check": False}
    row = _insert_pin(db_session, checks=[check])
    skip = {"memo", "updated_at"}
    before = {c.name: getattr(row, c.name) for c in PinRow.__table__.columns if c.name not in skip}
    assert _patch(app_client, str(row.id), {"memo": "고침"}).status_code == 200
    db_session.expire_all()
    row = db_session.get(PinRow, row.id)
    after = {c.name: getattr(row, c.name) for c in PinRow.__table__.columns if c.name not in skip}
    assert before == after and row.memo == "고침"


def test_live_pin_keeps_kakao_id_and_query_and_has_no_coordinates(app_client):
    pin = _live(app_client)
    body = _patch(app_client, pin["id"], {"category": "카페"}).json()
    assert (body["kakao_place_id"], body["search_query"], body["kind"]) == ("kakao:9001", "성수 곱창", "일반")
    assert not {"lat", "lng", "place_name"} & set(body)


# ---- 이벤트 ----

def test_pin_updated_event_has_the_pin_created_shape_without_my_reaction(app_client, db_session):
    pin = _live(app_client)
    _patch(app_client, pin["id"], {"memo": "웨이팅 길대"})
    events = _events(db_session, type="pin.updated")
    assert len(events) == 1
    payload = events[0].payload
    assert events[0].channel == "public" and payload["id"] == pin["id"] and payload["memo"] == "웨이팅 길대"
    assert "my_reaction" not in payload
    assert set(payload) == set(_events(db_session, type="pin.created")[0].payload)


def test_failed_edit_records_no_event(app_client, db_session):
    pin = _live(app_client)
    _patch(app_client, pin["id"], {"memo": "가" * 201})
    _patch(app_client, pin["id"], {"memo": "x"}, user="user_2")
    assert _events(db_session, type="pin.updated") == []


# ---- core (순수) ----

def test_validate_update_checks_kind_before_values():
    req = PinUpdateRequest(category="카페")
    with pytest.raises(AppError) as err:
        core.validate_update(kind="확정", source="live", reaction_count=0, req=req)
    assert err.value.code == "FORBIDDEN"


def test_can_edit_pin_needs_author_and_plain_kind():
    me, other = Principal("u1", "m", "member"), Principal("u2", "m", "member")
    pin = Resource(type="pin", map_id="m", author_id="u1", kind="일반")
    assert core.can_edit_pin(me, pin) and not core.can_edit_pin(other, pin)
    assert not core.can_edit_pin(Principal("u1", "m", "owner"), Resource(type="pin", map_id="m", author_id="u2", kind="일반"))
    for kind in ("AI추천", "확정"):
        assert not core.can_edit_pin(me, Resource(type="pin", map_id="m", author_id="u1", kind=kind))

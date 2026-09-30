"""#157 — 의견 목록·my_reaction·숙소 반응 차단·기타·AI 핀 필드·탈퇴용 반응 삭제."""

import pytest
from pydantic import ValidationError

from pins import api
from pins.models import Pin as PinRowAlias
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import _auth, _deny_membership, _events, _insert_pin
from authz.deps import get_membership_gateway
from main import app


def _react(client, pin, user, body=None):
    return client.put(f"/pins/{pin.id}/reaction", json=body or {"type": "like"}, cookies=_auth(user))


# ---- GET /pins/{pinId}/reactions ----

def test_get_reactions_returns_only_responders_with_display_name_and_chips(app_client, db_session):
    from auth.models import User
    db_session.add(User(id="user_2", display_name="민수", provider="kakao", provider_user_id="k2"))
    db_session.commit()
    pin = _insert_pin(db_session, place_id="r157_list")
    _react(app_client, pin, "user_2", {"type": "against", "reason_text": "멀어요", "reason_chip_ids": ["far"]})
    _react(app_client, pin, "user_1", {"type": "like"})

    resp = app_client.get(f"/pins/{pin.id}/reactions", cookies=_auth("user_1"))
    assert resp.status_code == 200
    body = resp.json()
    assert {r["user_id"] for r in body} == {"user_1", "user_2"}   # stranger는 반응 안 했으니 없다
    mine = next(r for r in body if r["user_id"] == "user_2")
    assert mine["type"] == "against"
    assert mine["reason_text"] == "멀어요"
    assert mine["reason_chip_ids"] == ["far"]
    assert mine["display_name"] == "민수"
    like = next(r for r in body if r["user_id"] == "user_1")
    assert "reason_text" not in like and "reason_chip_ids" not in like


def test_get_reactions_empty_when_nobody_reacted(app_client, db_session):
    pin = _insert_pin(db_session, place_id="r157_empty")
    resp = app_client.get(f"/pins/{pin.id}/reactions", cookies=_auth("user_1"))
    assert resp.status_code == 200 and resp.json() == []


def test_get_reactions_lodging_pin_is_empty_array(app_client, db_session):
    pin = _insert_pin(db_session, category="숙소", place_id="r157_lodging_list")
    resp = app_client.get(f"/pins/{pin.id}/reactions", cookies=_auth("user_1"))
    assert resp.status_code == 200 and resp.json() == []


def test_get_reactions_non_member_is_404(app_client, db_session):
    pin = _insert_pin(db_session, place_id="r157_nonmember")
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    resp = app_client.get(f"/pins/{pin.id}/reactions", cookies=_auth("outsider"))
    assert resp.status_code == 404


def test_get_reactions_other_users_private_pin_is_404(app_client, db_session):
    pin = _insert_pin(db_session, visibility="private", created_by="user_1", place_id="r157_private")
    resp = app_client.get(f"/pins/{pin.id}/reactions", cookies=_auth("user_2"))
    assert resp.status_code == 404


# ---- PUT 응답 모양 ----

def test_put_reaction_response_omits_reason_text_when_absent_and_echoes_chips(app_client, db_session):
    pin = _insert_pin(db_session, place_id="r157_put_shape")
    body = _react(app_client, pin, "user_2").json()
    assert "reason_text" not in body and "reason_chip_ids" not in body
    body = _react(app_client, pin, "user_2", {"type": "neutral", "reason_chip_ids": ["a"]}).json()
    assert body["reason_chip_ids"] == ["a"]


# ---- Pin.my_reaction ----

def test_list_pins_my_reaction_is_null_without_reaction_and_present_with(app_client, db_session):
    reacted = _insert_pin(db_session, place_id="r157_my_1")
    plain = _insert_pin(db_session, place_id="r157_my_2")
    _react(app_client, reacted, "user_2", {"type": "against", "reason_text": "별로"})
    _react(app_client, plain, "user_1")   # 남의 반응은 내 my_reaction이 아니다

    pins = {p["id"]: p for p in app_client.get("/maps/map_1/pins", cookies=_auth("user_2")).json()}
    assert pins[str(plain.id)]["my_reaction"] is None                      # 생략이 아니라 null
    mine = pins[str(reacted.id)]["my_reaction"]
    assert mine["type"] == "against" and mine["user_id"] == "user_2" and mine["reason_text"] == "별로"
    assert pins[str(reacted.id)]["reaction_summary"]["against"] == 1


def test_list_pins_my_reaction_uses_constant_number_of_queries(app_client, db_session):
    """핀 수가 늘어도 my_reaction 조회 쿼리는 늘지 않는다(N+1 금지)."""
    from sqlalchemy import event

    for i in range(6):
        pin = _insert_pin(db_session, place_id=f"r157_n1_{i}")
        _react(app_client, pin, "user_2")
    statements: list[str] = []

    def _count(conn, cursor, statement, *_):
        if "FROM reactions" in statement and "reactions.user_id" in statement:
            statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        app_client.get("/maps/map_1/pins", cookies=_auth("user_2"))
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(statements) == 1


def test_get_single_pin_response_includes_my_reaction(app_client, db_session):
    """shortlist가 쓰는 단건 경로(api.get_pin_response_for_viewer)도 my_reaction을 채운다."""
    pin = _insert_pin(db_session, place_id="r157_single")
    _react(app_client, pin, "user_2", {"type": "like"})
    from authz.core import Principal
    got = api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_2", principal=Principal("user_2", "map_1", "member")
    )
    assert got.my_reaction is not None and got.my_reaction.type == "like"
    other = api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_1", principal=Principal("user_1", "map_1", "member")
    )
    assert other.my_reaction is None


def test_public_events_never_carry_my_reaction(app_client, db_session):
    """my_reaction은 요청자 본인 값이라 전체 채널 이벤트 페이로드에 실리면 안 된다(가드레일 1)."""
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
        cookies=_auth("user_1"),
    )
    assert resp.status_code == 201
    assert resp.json()["my_reaction"] is None
    created = _events(db_session, type="pin.created")
    assert created and all("my_reaction" not in e.payload for e in created)
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="r157_evt", lat=35.1, lng=129.0, created_by="user_1"
    )
    assert "my_reaction" not in mutation.event.payload


# ---- 숙소 핀 반응 차단 ----

def test_lodging_pin_permissions_can_react_false_and_others_unchanged(app_client, db_session):
    lodging = _insert_pin(db_session, category="숙소", place_id="r157_lodge_perm")
    normal = _insert_pin(db_session, category="음식점", place_id="r157_normal_perm")
    pins = {p["id"]: p for p in app_client.get("/maps/map_1/pins", cookies=_auth("user_1")).json()}
    assert pins[str(lodging.id)]["permissions"]["can_react"] is False
    assert pins[str(lodging.id)]["permissions"]["can_delete"] is True
    assert pins[str(lodging.id)]["permissions"]["can_add_to_shortlist"] is True
    assert pins[str(normal.id)]["permissions"]["can_react"] is True


def test_put_reaction_on_lodging_pin_is_422_reaction_not_allowed(app_client, db_session):
    pin = _insert_pin(db_session, category="숙소", place_id="r157_lodge_put")
    resp = _react(app_client, pin, "user_2")
    assert resp.status_code == 422
    assert resp.json()["code"] == "REACTION_NOT_ALLOWED"
    assert db_session.query(ReactionRow).filter_by(pin_id=pin.id).count() == 0
    assert _events(db_session, type="reaction.changed") == []


def test_lodging_pin_against_without_reason_is_reaction_not_allowed_not_evidence_required(app_client, db_session):
    """대상 자체가 반응 불가이므로 사유 검증보다 먼저 거부한다."""
    pin = _insert_pin(db_session, category="숙소", place_id="r157_lodge_order")
    resp = _react(app_client, pin, "user_2", {"type": "against"})
    assert resp.json()["code"] == "REACTION_NOT_ALLOWED"


def test_delete_reaction_on_lodging_pin_is_204(app_client, db_session):
    pin = _insert_pin(db_session, category="숙소", place_id="r157_lodge_del")
    resp = app_client.delete(f"/pins/{pin.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 204


# ---- 「기타」 카테고리 ----

def test_create_and_filter_etc_category_pin_and_it_is_reactable(app_client, db_session):
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "기타", "source": "coordinate", "lat": 35.15, "lng": 129.12, "place_id": "r157_etc"},
        cookies=_auth("user_1"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["category"] == "기타" and body["permissions"]["can_react"] is True
    listed = app_client.get("/maps/map_1/pins", params={"category": "기타"}, cookies=_auth("user_1")).json()
    assert [p["id"] for p in listed] == [body["id"]]
    assert app_client.get("/maps/map_1/counts", cookies=_auth("user_1")).json()["by_category"]["기타"] == 1
    assert app_client.put(f"/pins/{body['id']}/reaction", json={"type": "like"}, cookies=_auth("user_2")).status_code == 200


# ---- AI 핀 reason / member_fulfillment / place_source ----

_FULFILLMENT = {"satisfied": 2, "total": 3, "by_member": [{"user_id": "user_1", "satisfied": True}]}
_SOURCE = {"provider": "kakao", "url": "https://place.map.kakao.com/1"}


def test_create_ai_pin_copies_reason_fulfillment_and_source_and_lists_them(app_client, db_session):
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="r157_ai", lat=35.1, lng=129.0, created_by="user_1",
        reason="다들 국물을 좋아해서", member_fulfillment=_FULFILLMENT, place_source=_SOURCE,
    )
    assert mutation.event.payload["reason"] == "다들 국물을 좋아해서"
    assert mutation.event.payload["member_fulfillment"] == _FULFILLMENT
    assert mutation.event.payload["place_source"] == _SOURCE
    db_session.commit()

    pin = app_client.get("/maps/map_1/pins", cookies=_auth("user_1")).json()[0]
    assert pin["reason"] == "다들 국물을 좋아해서"      # 게시된 뒤에도 유지(가드레일 5)
    assert pin["member_fulfillment"] == _FULFILLMENT
    assert pin["place_source"] == _SOURCE


def test_direct_pin_omits_ai_fields(app_client, db_session):
    _insert_pin(db_session, place_id="r157_direct")
    pin = app_client.get("/maps/map_1/pins", cookies=_auth("user_1")).json()[0]
    for key in ("reason", "member_fulfillment", "place_source"):
        assert key not in pin


def test_create_ai_pin_rejects_malformed_fulfillment_or_source(db_session):
    with pytest.raises(ValidationError):
        api.create_ai_pin(db_session, map_id="map_1", category="음식점", place_id="r157_bad1", lat=1, lng=1,
                          created_by="user_1", member_fulfillment={"satisfied": 1})
    with pytest.raises(ValidationError):
        api.create_ai_pin(db_session, map_id="map_1", category="음식점", place_id="r157_bad2", lat=1, lng=1,
                          created_by="user_1", place_source={"provider": "bing"})


# ---- 탈퇴용 delete_reactions_by_user ----

def test_delete_reactions_by_user_removes_only_that_users_reactions_and_returns_count(app_client, db_session):
    a = _insert_pin(db_session, place_id="r157_wd_a")
    b = _insert_pin(db_session, place_id="r157_wd_b")
    for pin in (a, b):
        _react(app_client, pin, "user_2")
    _react(app_client, a, "user_1")

    assert api.delete_reactions_by_user(db_session, user_id="user_2") == 2
    remaining = db_session.query(ReactionRow).all()
    assert [(str(r.pin_id), r.user_id) for r in remaining] == [(str(a.id), "user_1")]
    assert api.delete_reactions_by_user(db_session, user_id="user_2") == 0
    assert db_session.query(PinRowAlias).count() == 2   # 핀은 남는다

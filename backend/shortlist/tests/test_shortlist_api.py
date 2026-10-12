"""
실제 PostgreSQL+PostGIS가 필요한 통합 테스트(conftest.py 참고, docker-compose up -d 전제).
POST/DELETE /maps/{mapId}/shortlist·/shortlist/{itemId}가 mentor-review-plan.md의 결정대로
동작하는지 — 멱등, authz 교차-지도(Rule B), pins.kind 왕복, DetachedInstanceError 부재를
전부 실제 DB로 확인한다. 비구성원 응답은 403이 아니라 404다(pins/tests와 동일 관례,
docs/permissions.md "권한을 어디서 강제하는가").
"""

import uuid

from sqlalchemy import func, select

from auth.testing import session_cookie
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.events import EventLog
from main import app
from pins.models import Pin as PinRow


def _insert_pin(db_session, *, map_id="map_1", created_by="user_1", visibility="public",
                 kind="일반", origin="direct", place_id=None):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind=kind, origin=origin,
        place_id=place_id or f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.12, 35.15), 4326),
        visibility=visibility, created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _auth(user_id="user_1"):
    return session_cookie(user_id)


def _events(db_session, *, map_id="map_1", type=None):
    query = select(EventLog).where(EventLog.map_id == map_id)
    if type is not None:
        query = query.where(EventLog.type == type)
    return db_session.execute(query).scalars().all()


def _deny_membership():
    return FakeMembership({})


def test_confirm_pin_returns_201_with_shortlist_item(app_client, db_session):
    pin = _insert_pin(db_session)
    resp = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["pin"]["id"] == str(pin.id)
    assert body["added_by"] == "user_1"
    assert body["permissions"]["can_remove_from_shortlist"] is True


def test_confirm_pin_sets_pin_kind_to_confirmed(app_client, db_session):
    pin = _insert_pin(db_session, kind="일반")
    app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())

    db_session.refresh(pin)
    assert pin.kind == "확정"


def test_confirm_pin_twice_is_idempotent_no_duplicate_event(app_client, db_session):
    pin = _insert_pin(db_session)
    first = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    second = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth("user_2"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["added_by"] == "user_1"  # 최초 등록자 유지 — 재요청이 덮어쓰지 않는다

    events = _events(db_session, type="shortlist.changed")
    assert len(events) == 1  # 멱등 경로는 이벤트를 새로 만들지 않는다


def test_confirm_pin_cross_map_pin_id_is_404_not_500(app_client, db_session):
    """authz Rule B — 경로 mapId(=map_1)와 바디 pin_id가 가리키는 실제 지도(=map_2)가 다르면
    authz.core.can()의 ValueError(500)가 아니라 404여야 한다(mentor-review-plan.md 핵심 리스크)."""
    other_map_pin = _insert_pin(db_session, map_id="map_2")
    resp = app_client.post(
        "/maps/map_1/shortlist", json={"pin_id": str(other_map_pin.id)}, cookies=_auth(),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_confirm_pin_nonexistent_pin_is_404(app_client):
    resp = app_client.post(
        "/maps/map_1/shortlist", json={"pin_id": str(uuid.uuid4())}, cookies=_auth(),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_confirm_pin_non_member_is_404(app_client, db_session):
    pin = _insert_pin(db_session)
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_confirm_pin_publishes_shortlist_changed_event(app_client, db_session):
    pin = _insert_pin(db_session)
    resp = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = resp.json()["id"]

    events = _events(db_session, type="shortlist.changed")
    assert len(events) == 1
    assert events[0].channel == "public"
    assert events[0].payload["action"] == "added"
    assert events[0].payload["item"]["id"] == item_id


def test_get_shortlist_lists_confirmed_items(app_client, db_session):
    pin = _insert_pin(db_session)
    app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())

    resp = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["pin"]["kind"] == "확정"


def test_get_shortlist_non_member_is_404(app_client, db_session):
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404


def test_unconfirm_pin_returns_204_and_restores_kind_for_ai_origin(app_client, db_session):
    pin = _insert_pin(db_session, kind="AI추천", origin="ai")
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = confirm.json()["id"]

    resp = app_client.delete(f"/shortlist/{item_id}", cookies=_auth())
    assert resp.status_code == 204

    db_session.refresh(pin)
    assert pin.kind == "AI추천"  # origin='ai' 기준으로 복원(core.kind_after_unconfirm)


def test_unconfirm_pin_restores_kind_for_direct_origin(app_client, db_session):
    pin = _insert_pin(db_session, kind="일반", origin="direct")
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = confirm.json()["id"]

    app_client.delete(f"/shortlist/{item_id}", cookies=_auth())

    db_session.refresh(pin)
    assert pin.kind == "일반"


def test_unconfirm_pin_then_reconfirm_round_trips_kind(app_client, db_session):
    pin = _insert_pin(db_session, kind="일반", origin="direct")
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    app_client.delete(f"/shortlist/{confirm.json()['id']}", cookies=_auth())

    reconfirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    assert reconfirm.status_code == 201

    db_session.refresh(pin)
    assert pin.kind == "확정"


def test_unconfirm_nonexistent_item_is_404(app_client):
    resp = app_client.delete(f"/shortlist/{uuid.uuid4()}", cookies=_auth())
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_unconfirm_pin_non_member_of_items_map_is_404(app_client, db_session):
    """비구성원이 다른 지도의 확정 항목을 DELETE — item.map_id 기준으로 멤버십 판정하므로
    Rule A(로더가 읽은 행의 map_id만 쓴다)가 자동으로 지켜진다. 이 프로젝트 관례대로 403이
    아니라 404다(pins/tests::test_delete_pin_non_member_is_404, docs/permissions.md)."""
    pin = _insert_pin(db_session)
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = confirm.json()["id"]

    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.delete(f"/shortlist/{item_id}", cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_unconfirm_pin_publishes_shortlist_changed_removed_event(app_client, db_session):
    pin = _insert_pin(db_session)
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = confirm.json()["id"]

    resp = app_client.delete(f"/shortlist/{item_id}", cookies=_auth())
    assert resp.status_code == 204

    events = _events(db_session, type="shortlist.changed")
    assert len(events) == 2  # added + removed
    assert events[-1].payload["action"] == "removed"
    assert events[-1].payload["item"]["id"] == item_id


def test_unconfirm_pin_survives_delete_then_pin_access_no_detached_instance_error(app_client, db_session):
    """DeepSeek 검수 지적(mentor-review-plan.md) — delete_item 이후 item 속성(pin_id/map_id/
    이벤트 payload)에 접근해도 DetachedInstanceError 없이 실제 commit까지 끝나야 한다."""
    pin = _insert_pin(db_session, kind="일반", origin="direct")
    confirm = app_client.post("/maps/map_1/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
    item_id = confirm.json()["id"]

    resp = app_client.delete(f"/shortlist/{item_id}", cookies=_auth())
    assert resp.status_code == 204  # 500이면 DetachedInstanceError 등으로 죽은 것

    # 커밋 이후 상태까지 실제로 확인 — 세이브포인트가 아니라 진짜 delete+flush 조합에서 깨지는지.
    listed = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    assert listed.json() == []


# --- PUT /maps/{mapId}/shortlist/order (#142) ---

def _confirm(app_client, db_session, n=3, *, map_id="map_1"):
    ids = []
    for _ in range(n):
        pin = _insert_pin(db_session, map_id=map_id)
        resp = app_client.post(f"/maps/{map_id}/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth())
        ids.append(resp.json()["id"])
    return ids


def test_reorder_returns_items_in_requested_order_and_get_reflects_it(app_client, db_session):
    a, b, c = _confirm(app_client, db_session)
    resp = app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [c, a, b]}, cookies=_auth("user_2"))

    assert resp.status_code == 200
    assert [i["id"] for i in resp.json()] == [c, a, b]
    assert [i["visit_order"] for i in resp.json()] == [0, 1, 2]
    got = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    assert [i["id"] for i in got.json()] == [c, a, b]


def test_reorder_missing_item_is_422(app_client, db_session):
    a, b, c = _confirm(app_client, db_session)
    # 같은 트랜잭션에서 확정하면 added_at이 같아 초기 순서는 id 순이다 — 요청 전 GET을 기준으로 삼는다
    before = [i["id"] for i in app_client.get("/maps/map_1/shortlist", cookies=_auth()).json()]
    resp = app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [a, b]}, cookies=_auth())
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    got = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    assert [i["id"] for i in got.json()] == before  # 실패한 요청은 아무것도 바꾸지 않는다


def test_reorder_duplicate_item_is_422(app_client, db_session):
    a, b = _confirm(app_client, db_session, n=2)
    resp = app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [a, a, b]}, cookies=_auth())
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_reorder_item_from_other_map_is_422(app_client, db_session):
    a, b = _confirm(app_client, db_session, n=2)
    other = _insert_pin(db_session, map_id="map_2")
    from shortlist import service
    foreign = service.add_item(db_session, map_id="map_2", pin_id=str(other.id), added_by="user_1")[0]
    resp = app_client.put(
        "/maps/map_1/shortlist/order", json={"item_ids": [a, str(foreign.id)]}, cookies=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_reorder_unknown_or_malformed_id_is_422(app_client, db_session):
    a, = _confirm(app_client, db_session, n=1)
    resp = app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [a, "not-a-uuid"]}, cookies=_auth())
    assert resp.status_code == 422


def test_reorder_non_member_is_404(app_client, db_session):
    a, = _confirm(app_client, db_session, n=1)
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    resp = app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [a]}, cookies=_auth("outsider"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_reorder_records_reordered_event_per_item_in_same_commit(app_client, db_session):
    a, b = _confirm(app_client, db_session, n=2)
    before = len(_events(db_session, type="shortlist.changed"))
    app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [b, a]}, cookies=_auth())

    events = _events(db_session, type="shortlist.changed")[before:]
    assert {e.payload["action"] for e in events} == {"reordered"}
    by_item = {e.payload["item"]["id"]: e.payload["item"]["visit_order"] for e in events}
    assert by_item == {b: 0, a: 1}


def test_reorder_does_not_touch_routes_or_emit_route_event(app_client, db_session):
    a, b = _confirm(app_client, db_session, n=2)
    app_client.post("/maps/map_1/route", cookies=_auth())
    routes_before = app_client.get("/maps/map_1/route", cookies=_auth()).json()
    route_events_before = len(_events(db_session, type="route.recalculated"))

    app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [b, a]}, cookies=_auth())

    assert app_client.get("/maps/map_1/route", cookies=_auth()).json() == routes_before
    assert len(_events(db_session, type="route.recalculated")) == route_events_before


def test_new_item_after_reorder_goes_last(app_client, db_session):
    a, b = _confirm(app_client, db_session, n=2)
    app_client.put("/maps/map_1/shortlist/order", json={"item_ids": [b, a]}, cookies=_auth())
    c, = _confirm(app_client, db_session, n=1)
    got = app_client.get("/maps/map_1/shortlist", cookies=_auth())
    assert [i["id"] for i in got.json()] == [b, a, c]

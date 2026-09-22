"""
실제 PostgreSQL+PostGIS가 필요한 통합 테스트(conftest.py 참고). GET/POST /maps/{mapId}/route
(#103)가 docs/api-spec.yaml·docs/events.md 계약대로 동작하는지 확인한다. 확정 리스트 자체의
CRUD 회귀는 test_shortlist_api.py가 이미 다루므로 여기서는 route 전용 시나리오만 본다.

shortlist/CLAUDE.md 완료 정의: "여러 지역에 걸친 확정 핀 입력 시 지역별로 별도 동선이 나오는지
테스트 (8km 이상 떨어진 두 클러스터 케이스)"를 test_post_route_splits_far_apart_pins_into_
separate_regions가 실제 엔드포인트로 확인한다(순수 계산 버전은 test_routing.py 참고).
"""

import uuid

from sqlalchemy import func, select

from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.events import EventLog
from main import app
from pins.models import Pin as PinRow


def _insert_confirmed_pin(db_session, *, map_id="map_1", lat, lng, created_by="user_1"):
    """확정(kind='확정') 핀을 직접 심는다 — POST /maps/{mapId}/shortlist를 거치지 않고 좌표를
    자유롭게 지정하려고 pins 테이블에 바로 넣는다(shortlist_items 행도 함께 필요하면 호출부가
    app_client.post(".../shortlist")로 별도 확정한다)."""
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="관광지", kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        visibility="public", created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _auth(user_id="user_1"):
    return {"session": user_id}


def _confirm(app_client, pin, *, map_id="map_1", user_id="user_1"):
    resp = app_client.post(f"/maps/{map_id}/shortlist", json={"pin_id": str(pin.id)}, cookies=_auth(user_id))
    assert resp.status_code == 201
    return resp


def _deny_membership():
    return FakeMembership({})


def test_get_route_before_any_post_returns_empty_list(app_client):
    resp = app_client.get("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_route_non_member_is_404(app_client):
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.get("/maps/map_1/route", cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404


def test_post_route_non_member_is_404(app_client):
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.post("/maps/map_1/route", cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404


def test_post_route_with_no_confirmed_pins_returns_empty_list(app_client):
    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_route_computes_single_region_for_nearby_pins(app_client, db_session):
    pin_a = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    pin_b = _insert_confirmed_pin(db_session, lat=35.1590, lng=129.0600)
    _confirm(app_client, pin_a)
    _confirm(app_client, pin_b)

    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    routes = resp.json()
    assert len(routes) == 1
    assert set(routes[0]["ordered_pin_ids"]) == {str(pin_a.id), str(pin_b.id)}
    assert len(routes[0]["legs"]) == 1
    assert routes[0]["total_distance_m"] > 0


def test_post_route_splits_far_apart_pins_into_separate_regions(app_client, db_session):
    """완료 정의 — 8km 이상 떨어진 두 클러스터는 별도 동선(Route)이 된다."""
    near_a1 = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    near_a2 = _insert_confirmed_pin(db_session, lat=35.1585, lng=129.0595)
    far_b1 = _insert_confirmed_pin(db_session, lat=35.2380, lng=129.0590)  # a1과 약 8.9km
    for pin in (near_a1, near_a2, far_b1):
        _confirm(app_client, pin)

    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    routes = resp.json()
    assert len(routes) == 2

    pin_id_sets = [set(r["ordered_pin_ids"]) for r in routes]
    assert {str(near_a1.id), str(near_a2.id)} in pin_id_sets
    assert {str(far_b1.id)} in pin_id_sets


def test_get_route_returns_last_computed_result(app_client, db_session):
    pin = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin)
    posted = app_client.post("/maps/map_1/route", cookies=_auth())

    resp = app_client.get("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json() == posted.json()


def test_get_route_does_not_recalculate(app_client, db_session):
    """GET은 확정 리스트가 바뀌어도 재계산하지 않는다 — POST로 다시 불러야 반영된다
    (shortlist/CLAUDE.md "책임": 수동 트리거로만 재계산)."""
    pin_a = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin_a)
    app_client.post("/maps/map_1/route", cookies=_auth())

    pin_b = _insert_confirmed_pin(db_session, lat=35.2380, lng=129.0590)
    _confirm(app_client, pin_b)  # 확정 리스트는 바뀌었지만 route는 아직 재계산 안 됨

    resp = app_client.get("/maps/map_1/route", cookies=_auth())
    assert len(resp.json()) == 1  # 여전히 pin_a만 반영된 이전 결과
    assert resp.json()[0]["ordered_pin_ids"] == [str(pin_a.id)]


def test_post_route_after_shortlist_change_reflects_new_pin(app_client, db_session):
    pin_a = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin_a)
    app_client.post("/maps/map_1/route", cookies=_auth())

    pin_b = _insert_confirmed_pin(db_session, lat=35.1585, lng=129.0595)
    _confirm(app_client, pin_b)

    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert len(resp.json()) == 1
    assert set(resp.json()[0]["ordered_pin_ids"]) == {str(pin_a.id), str(pin_b.id)}


def test_post_route_replaces_previous_batch_not_appends(app_client, db_session):
    pin_a = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin_a)
    app_client.post("/maps/map_1/route", cookies=_auth())

    # 확정 리스트에서 유일한 핀을 빼면 재계산 시 route는 빈 배열이어야 한다(누적되지 않는다).
    listed = app_client.get("/maps/map_1/shortlist", cookies=_auth()).json()
    app_client.delete(f"/shortlist/{listed[0]['id']}", cookies=_auth())

    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert resp.json() == []
    assert app_client.get("/maps/map_1/route", cookies=_auth()).json() == []


def test_post_route_scoped_to_map(app_client, db_session):
    """conftest 기본 FakeMembership은 map_1만 등록돼 있다 — map_2 확정을 만들려면 이 테스트
    안에서만 map_2 멤버십도 임시로 허용한다. app_client 픽스처 teardown이 테스트가 끝나면
    dependency_overrides를 통째로 clear하므로 되돌릴 필요는 없다."""
    pin_map1 = _insert_confirmed_pin(db_session, map_id="map_1", lat=35.1580, lng=129.0590)
    pin_map2 = _insert_confirmed_pin(db_session, map_id="map_2", lat=35.1580, lng=129.0590)

    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership(
        {("map_1", "user_1"): "member", ("map_2", "user_1"): "member"}
    )
    _confirm(app_client, pin_map1, map_id="map_1")
    _confirm(app_client, pin_map2, map_id="map_2")

    resp = app_client.post("/maps/map_1/route", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json()[0]["ordered_pin_ids"] == [str(pin_map1.id)]  # map_2 데이터가 새지 않는다


def test_post_route_publishes_route_recalculated_event(app_client, db_session):
    pin = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin)

    app_client.post("/maps/map_1/route", cookies=_auth())

    events = db_session.execute(
        select(EventLog).where(EventLog.map_id == "map_1", EventLog.type == "route.recalculated")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].channel == "public"
    assert isinstance(events[0].payload, list)  # docs/events.md — data는 Route[] 그대로, 객체로 안 감쌈
    assert events[0].payload[0]["ordered_pin_ids"] == [str(pin.id)]


def test_get_route_does_not_publish_event(app_client, db_session):
    pin = _insert_confirmed_pin(db_session, lat=35.1580, lng=129.0590)
    _confirm(app_client, pin)
    app_client.post("/maps/map_1/route", cookies=_auth())

    app_client.get("/maps/map_1/route", cookies=_auth())

    events = db_session.execute(
        select(EventLog).where(EventLog.map_id == "map_1", EventLog.type == "route.recalculated")
    ).scalars().all()
    assert len(events) == 1  # POST 한 번만 — GET은 이벤트를 새로 만들지 않는다

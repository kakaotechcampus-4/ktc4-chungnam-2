"""
실제 PostgreSQL+PostGIS가 필요한 통합 테스트(conftest.py 참고, docker-compose up -d 전제).
가드레일 1(비공개 후보 유출 금지)과 계약(409 detail.pin_id, soft delete) 회귀를 고정한다.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from main import app
from pins.deps import get_event_publisher, get_membership_gateway
from pins.models import Pin as PinRow


def _insert_pin(db_session, *, map_id="map_1", place_id=None, created_by="user_1",
                 visibility="public", kind="일반", category="음식점", deleted=False):
    row = PinRow(
        id=uuid.uuid4(),
        map_id=map_id,
        category=category,
        kind=kind,
        origin="direct",
        place_id=place_id or f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.12, 35.15), 4326),
        visibility=visibility,
        created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    if deleted:
        row.deleted_at = datetime.now(timezone.utc)
        db_session.commit()
    return row


class SpyPublisher:
    def __init__(self):
        self.events = []

    def publish(self, map_id, channel, type, payload):
        self.events.append((map_id, channel, type, payload))


def _auth(user_id="user_1"):
    return {"session": user_id}


def test_create_pin_returns_201(app_client):
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
        cookies=_auth(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"] == "음식점"
    assert body["kind"] == "일반"
    assert body["visibility"] == "public"


def test_create_pin_without_cookie_is_401(app_client):
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_create_pin_duplicate_place_id_is_409_with_existing_pin_id(app_client, db_session):
    existing = _insert_pin(db_session, place_id="dup_place")
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "search", "place_id": "dup_place", "lat": 35.1, "lng": 129.0},
        cookies=_auth(),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "PIN_DUPLICATE"
    assert body["detail"]["pin_id"] == str(existing.id)


def test_create_pin_reuses_place_id_after_soft_delete(app_client, db_session):
    """부분 유니크가 deleted_at IS NULL 조건을 실제로 타는지 — 삭제된 자리엔 다시 찍을 수 있다."""
    _insert_pin(db_session, place_id="freed_place", deleted=True)
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "search", "place_id": "freed_place", "lat": 35.1, "lng": 129.0},
        cookies=_auth(),
    )
    assert resp.status_code == 201


def test_list_pins_hides_other_users_private_pin(app_client, db_session):
    """가드레일 1 — 남이 요청한 비공개 AI 후보는 목록에 나오면 안 된다."""
    _insert_pin(db_session, created_by="stranger", visibility="private", place_id="secret")
    resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pins_shows_own_private_pin(app_client, db_session):
    _insert_pin(db_session, created_by="user_1", visibility="private", place_id="my_secret")
    resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_pins_hides_soft_deleted_other_users_private_pin(app_client, db_session):
    """AND/OR 괄호 회귀 테스트 — 삭제된 남의 비공개 핀이 새어나오면 안 된다."""
    _insert_pin(db_session, created_by="stranger", visibility="private", place_id="deleted_secret", deleted=True)
    resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pins_filters_by_category_kind_and_created_by(app_client, db_session):
    _insert_pin(db_session, category="음식점", kind="일반", created_by="user_1", place_id="a")
    _insert_pin(db_session, category="카페", kind="일반", created_by="user_2", place_id="b")

    resp = app_client.get("/maps/map_1/pins?category=카페", cookies=_auth())
    assert [p["category"] for p in resp.json()] == ["카페"]

    resp = app_client.get("/maps/map_1/pins?created_by=user_1&created_by=user_2", cookies=_auth())
    assert len(resp.json()) == 2


def test_delete_pin_soft_deletes_and_hides_from_list(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="to_delete")
    resp = app_client.delete(f"/pins/{row.id}", cookies=_auth("user_1"))
    assert resp.status_code == 204

    listed = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert listed.json() == []


def test_delete_nonexistent_pin_is_404(app_client):
    resp = app_client.delete(f"/pins/{uuid.uuid4()}", cookies=_auth())
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_create_pin_publishes_event_for_public_pin(app_client):
    spy = SpyPublisher()
    app.dependency_overrides[get_event_publisher] = lambda: spy
    try:
        app_client.post(
            "/maps/map_1/pins",
            json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
            cookies=_auth(),
        )
    finally:
        del app.dependency_overrides[get_event_publisher]

    assert len(spy.events) == 1
    _map_id, channel, event_type, _payload = spy.events[0]
    assert channel == "public"
    assert event_type == "pin.created"


def test_delete_pin_publishes_event_for_public_pin(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="to_delete_event")
    spy = SpyPublisher()
    app.dependency_overrides[get_event_publisher] = lambda: spy
    try:
        app_client.delete(f"/pins/{row.id}", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_event_publisher]

    assert len(spy.events) == 1
    assert spy.events[0][2] == "pin.deleted"
    assert spy.events[0][3] == {"pin_id": str(row.id)}


def test_delete_pin_forbidden_when_not_member(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="not_my_map")
    app.dependency_overrides[get_membership_gateway] = lambda: _AlwaysDenyMembership()
    try:
        resp = app_client.delete(f"/pins/{row.id}", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


class _AlwaysDenyMembership:
    def is_member(self, map_id, user_id):
        return False

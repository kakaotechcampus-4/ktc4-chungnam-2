"""
실제 PostgreSQL+PostGIS가 필요한 통합 테스트(conftest.py 참고, docker-compose up -d 전제).
가드레일 1(비공개 후보 유출 금지)과 계약(409 detail.pin_id, soft delete) 회귀를 고정한다.

비구성원 응답은 403이 아니라 404다(docs/CHANGELOG-api.md 2026-09-11, PR #71 멘토 리뷰 대응) —
authz.guard.require*()가 존재를 흘리지 않으려고 비구성원을 전부 404로 막는다. 이벤트 발행은
publisher 스파이가 아니라 event_log 테이블을 직접 조회해 확인한다(record_event가 같은 세션에
쓰기 때문에 db_session으로 그대로 보인다).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.events import EventLog
from main import app
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


def _auth(user_id="user_1"):
    return {"session": user_id}


def _events(db_session, *, map_id="map_1", type=None):
    query = select(EventLog).where(EventLog.map_id == map_id)
    if type is not None:
        query = query.where(EventLog.type == type)
    return db_session.execute(query).scalars().all()


def _deny_membership():
    """비구성원 취급 — authz.deps.get_membership_gateway를 오버라이드한다(pins는 더 이상
    자기 멤버십 게이트를 갖지 않는다)."""
    return FakeMembership({})


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


def test_create_pin_non_member_is_404(app_client):
    """issue #61 — 비구성원이 핀을 생성할 수 있던 비대칭을 구조적으로 닫는다."""
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.post(
            "/maps/map_1/pins",
            json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
            cookies=_auth(),
        )
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


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


def test_create_pin_recovers_from_real_db_constraint_violation(db_session, monkeypatch):
    """사전조회(_find_existing_pin_id)가 놓친 경우(레이스)를 흉내내 실제 PostgreSQL 유니크
    제약 위반을 강제로 유발한다. begin_nested()만으로는 Session이 deactive 상태로 남아
    이후 쿼리가 PendingRollbackError로 죽는다는 걸 실측으로 확인한 회귀 테스트 —
    db.rollback()을 함께 불러야 여기서 실제로 복구된다(service.py::create_pin 참고)."""
    from authz.core import Principal
    from pins import service
    from pins.ports import ResolvedPlace
    from pins.schemas import PinCreateRequest

    existing = _insert_pin(db_session, place_id="race_place")

    # 사전조회가 항상 "안 겹침"으로 보이게 만들어 실제 INSERT까지 가게 한다(레이스 재현).
    monkeypatch.setattr(service, "_find_existing_pin_id", lambda db, map_id, place_id: None)

    class _FixedPlaces:
        def resolve(self, draft):
            return ResolvedPlace(place_id="race_place", lat=35.1, lng=129.0)

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    req = PinCreateRequest(category="음식점", source="coordinate", lat=35.1, lng=129.0)

    from common.errors import AppError

    try:
        service.create_pin(db_session, "map_1", principal, req, _FixedPlaces())
        raise AssertionError("PIN_DUPLICATE가 발생했어야 한다")
    except AppError as exc:
        assert exc.code == "PIN_DUPLICATE"

    # 세션이 실제로 복구됐는지 — 복구 안 됐으면 아래 쿼리가 PendingRollbackError로 죽는다.
    rows = db_session.execute(select(PinRow).where(PinRow.id == existing.id)).scalars().all()
    assert len(rows) == 1


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


def test_list_pins_non_member_is_404(app_client, db_session):
    _insert_pin(db_session, created_by="user_1")
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


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


def test_create_pin_publishes_event_for_public_pin(app_client, db_session):
    resp = app_client.post(
        "/maps/map_1/pins",
        json={"category": "음식점", "source": "coordinate", "lat": 35.15, "lng": 129.12},
        cookies=_auth(),
    )
    pin_id = resp.json()["id"]

    events = _events(db_session, type="pin.created")
    assert len(events) == 1
    assert events[0].channel == "public"
    assert events[0].payload["id"] == pin_id


def test_delete_pin_publishes_event_for_public_pin(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="to_delete_event")
    resp = app_client.delete(f"/pins/{row.id}", cookies=_auth("user_1"))
    assert resp.status_code == 204

    events = _events(db_session, type="pin.deleted")
    assert len(events) == 1
    assert events[0].payload == {"pin_id": str(row.id)}


def test_delete_pin_non_member_is_404(app_client, db_session):
    """비구성원 응답은 403이 아니라 404다(docs/CHANGELOG-api.md 2026-09-11)."""
    row = _insert_pin(db_session, created_by="user_1", place_id="not_my_map")
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.delete(f"/pins/{row.id}", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def _reaction_summary_of(app_client, pin_id, user="user_1"):
    pins = app_client.get("/maps/map_1/pins", cookies=_auth(user)).json()
    return next(p["reaction_summary"] for p in pins if p["id"] == pin_id)


def test_put_reaction_against_without_reason_is_422(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_1")
    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "against"}, cookies=_auth("user_2"))
    assert resp.status_code == 422
    assert resp.json()["code"] == "EVIDENCE_REQUIRED"


def test_put_reaction_against_with_whitespace_reason_is_422(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_ws")
    resp = app_client.put(
        f"/pins/{row.id}/reaction", json={"type": "against", "reason_text": "   "}, cookies=_auth("user_2")
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "EVIDENCE_REQUIRED"


def test_put_reaction_like_without_reason_is_200(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_2")
    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "like"
    assert body["pin_id"] == str(row.id)
    assert body["user_id"] == "user_2"


def test_put_reaction_against_with_chip_ids_only_is_200(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_chip")
    resp = app_client.put(
        f"/pins/{row.id}/reaction",
        json={"type": "against", "reason_chip_ids": ["spicy_focused"]},
        cookies=_auth("user_2"),
    )
    assert resp.status_code == 200


def test_put_reaction_twice_upserts_single_row(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_upsert")
    app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))

    summary = _reaction_summary_of(app_client, str(row.id))
    assert summary["like"] == 1


def test_put_reaction_type_change_still_requires_reason_for_against(app_client, db_session):
    """반응 타입 전환 — 이전에 사유 없이 통과했다고 재검증을 건너뛰지 않는다."""
    row = _insert_pin(db_session, created_by="user_1", place_id="react_switch")
    app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))

    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "against"}, cookies=_auth("user_2"))
    assert resp.status_code == 422

    resp = app_client.put(
        f"/pins/{row.id}/reaction", json={"type": "against", "reason_text": "매워요"}, cookies=_auth("user_2")
    )
    assert resp.status_code == 200

    summary = _reaction_summary_of(app_client, str(row.id))
    assert summary["like"] == 0
    assert summary["against"] == 1


def test_delete_reaction_removes_row_and_decrements_summary(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_delete")
    app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    assert _reaction_summary_of(app_client, str(row.id))["like"] == 1

    resp = app_client.delete(f"/pins/{row.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 204
    assert _reaction_summary_of(app_client, str(row.id))["like"] == 0


def test_delete_reaction_when_none_exists_is_still_204(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_noop_delete")
    resp = app_client.delete(f"/pins/{row.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 204


def test_put_reaction_on_nonexistent_pin_is_404(app_client):
    resp = app_client.put(f"/pins/{uuid.uuid4()}/reaction", json={"type": "like"}, cookies=_auth())
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_delete_reaction_on_nonexistent_pin_is_404(app_client):
    resp = app_client.delete(f"/pins/{uuid.uuid4()}/reaction", cookies=_auth())
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_put_reaction_non_member_is_404(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_forbidden")
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_put_reaction_on_other_users_private_pin_is_404_regardless_of_membership(app_client, db_session):
    """가드레일 1 — 비공개 접근 차단이 구성원 확인보다 먼저다(pins/loaders.py::load_pin이
    authz.guard보다 먼저 실행된다). 구성원이어도 남의 비공개 핀엔 못 붙는다."""
    row = _insert_pin(db_session, created_by="user_1", visibility="private", place_id="react_private")

    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "AI_PIN_PRIVATE"

    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404
    assert resp.json()["code"] == "AI_PIN_PRIVATE"


def test_delete_reaction_on_other_users_private_pin_is_404(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", visibility="private", place_id="react_private_del")
    resp = app_client.delete(f"/pins/{row.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "AI_PIN_PRIVATE"


def test_put_reaction_on_own_private_pin_succeeds(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", visibility="private", place_id="react_own_private")
    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_1"))
    assert resp.status_code == 200


def test_put_reaction_publishes_event_for_public_pin(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_event")
    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))
    assert resp.status_code == 200

    events = _events(db_session, type="reaction.changed")
    assert len(events) == 1
    assert events[0].channel == "public"
    assert events[0].payload == {"pin_id": str(row.id), "reaction_summary": {"like": 1, "neutral": 0, "against": 0}}


def test_put_reaction_on_own_private_pin_emits_no_event(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", visibility="private", place_id="react_private_event")
    resp = app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_1"))
    assert resp.status_code == 200

    assert _events(db_session, type="reaction.changed") == []


def test_delete_reaction_emits_event_only_when_row_existed(app_client, db_session):
    row = _insert_pin(db_session, created_by="user_1", place_id="react_delete_event")
    app_client.put(f"/pins/{row.id}/reaction", json={"type": "like"}, cookies=_auth("user_2"))

    resp = app_client.delete(f"/pins/{row.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 204
    # PUT에서 1건 + 이번 DELETE(반응이 실제로 있었다)에서 1건 = 2건.
    assert len(_events(db_session, type="reaction.changed")) == 2

    # 이미 지워진 반응을 다시 DELETE — 상태 변화가 없으므로 새 이벤트는 없다(그대로 2건).
    resp = app_client.delete(f"/pins/{row.id}/reaction", cookies=_auth("user_2"))
    assert resp.status_code == 204
    assert len(_events(db_session, type="reaction.changed")) == 2

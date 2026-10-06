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

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select

from auth.testing import ensure_users, session_cookie
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.events import EventLog
from main import app
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow


def _insert_pin(db_session, *, map_id="map_1", place_id=None, created_by="user_1",
                 visibility="public", kind="일반", category="음식점", deleted=False, checks=None):
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
        checks=checks,
    )
    db_session.add(row)
    db_session.commit()
    if deleted:
        row.deleted_at = datetime.now(timezone.utc)
        db_session.commit()
    return row


# 검색 결과를 골라 핀을 만드는 요청 본문 — 값은 places.testing.FakePlaces의 샘플 장소와 같다(#195).
# place_id는 카카오 검색 결과의 ID(매칭 힌트)이고 핀에는 저장되지 않는다.
KALGUKSU = {"category": "음식점", "place_id": "kakao:1001", "place_name": "성수 칼국수", "lat": 37.5445, "lng": 127.0561}
CAFE = {"category": "카페", "place_id": "kakao:1002", "place_name": "온도 커피 성수", "lat": 37.5439, "lng": 127.0556}


def _auth(user_id="user_1"):
    return session_cookie(user_id)


def _events(db_session, *, map_id="map_1", type=None):
    query = select(EventLog).where(EventLog.map_id == map_id)
    if type is not None:
        query = query.where(EventLog.type == type)
    return db_session.execute(query).scalars().all()


def _deny_membership():
    """비구성원 취급 — authz.deps.get_membership_gateway를 오버라이드한다(pins는 더 이상
    자기 멤버십 게이트를 갖지 않는다)."""
    return FakeMembership({})


def test_create_pin_returns_201_with_places_name_and_coordinates(app_client, fake_places):
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"] == "음식점"
    assert body["kind"] == "일반"
    assert body["visibility"] == "public"
    assert body["place_name"] == "성수 칼국수"
    assert (body["lat"], body["lng"]) == (37.5445, 127.0561)


def test_create_pin_uses_place_values_not_request_values(app_client, db_session, fake_places):
    """#195 완료 조건 — 요청의 이름·좌표(카카오 값)는 저장되지 않는다. 핀의 이름·좌표는 장소의 것이다."""
    body = {**KALGUKSU, "place_name": "성수 칼국수 (본점)", "lat": 37.5447, "lng": 127.0563}   # 카카오가 준 약간 다른 값
    resp = app_client.post("/maps/map_1/pins", json=body, cookies=_auth())
    assert resp.status_code == 201
    assert resp.json()["place_name"] == "성수 칼국수"
    assert (resp.json()["lat"], resp.json()["lng"]) == (37.5445, 127.0561)

    row = db_session.execute(select(PinRow)).scalar_one()
    assert row.place_id == fake_places.place_id("seongsu-kalguksu")      # places.id — 카카오 ID가 아니다
    assert "place_name" not in PinRow.__table__.columns                  # 이름 컬럼 자체가 없다
    geometry = cast(PinRow.geom, Geometry())
    lng, lat = db_session.execute(select(func.ST_X(geometry), func.ST_Y(geometry))).one()
    assert (round(lat, 4), round(lng, 4)) == (37.5445, 127.0561)         # 장소 좌표의 복사


def test_create_pin_records_kakao_id_and_url_on_the_place_and_returns_place_url(app_client, fake_places):
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    assert resp.status_code == 201
    row = fake_places._row(fake_places.place_id("seongsu-kalguksu"))
    assert row.kakao_place_id == "kakao:1001"
    assert row.kakao_place_url == "https://place.map.kakao.com/1001"
    assert resp.json()["place_url"] == "https://place.map.kakao.com/1001"
    listed = app_client.get("/maps/map_1/pins", cookies=_auth()).json()
    assert listed[0]["place_url"] == "https://place.map.kakao.com/1001" and listed[0]["place_name"] == "성수 칼국수"


def test_create_pin_with_non_kakao_id_records_nothing_and_omits_place_url(app_client, fake_places):
    resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "place_id": "naver:77"}, cookies=_auth())
    assert resp.status_code == 201
    assert "place_url" not in resp.json()
    assert fake_places._row(fake_places.place_id("seongsu-kalguksu")).kakao_place_id is None


def test_create_pin_without_matching_place_is_422_place_not_supported(app_client, db_session, fake_places):
    far = {**KALGUKSU, "place_name": "없는 가게", "lat": 35.0, "lng": 129.0}
    resp = app_client.post("/maps/map_1/pins", json=far, cookies=_auth())
    assert resp.status_code == 422
    assert resp.json()["code"] == "PLACE_NOT_SUPPORTED"
    assert db_session.execute(select(func.count()).select_from(PinRow)).scalar_one() == 0
    assert all(r.kakao_place_id is None for r in fake_places.rows)   # 실패한 요청이 카카오 ID를 남기지 않는다


@pytest.mark.parametrize("category", ["숙소", "기타"])
def test_create_pin_lodging_and_etc_are_not_supported(app_client, category):
    resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "category": category}, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "PLACE_NOT_SUPPORTED"


def test_create_pin_closed_place_is_not_supported(app_client):
    closed = {"category": "음식점", "place_id": "kakao:9", "place_name": "종로 옛날국수", "lat": 37.5704, "lng": 126.9920}
    resp = app_client.post("/maps/map_1/pins", json=closed, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "PLACE_NOT_SUPPORTED"


def test_create_pin_wrong_category_for_the_place_is_rejected(app_client, db_session):
    """분류가 장소와 다르면 짝을 찾지 못하므로 핀을 만들지 않는다(엉뚱한 곳에 꽂지 않는다)."""
    resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "category": "카페"}, cookies=_auth())
    assert resp.status_code == 422
    assert resp.json()["code"] in ("PLACE_NOT_SUPPORTED", "VALIDATION_ERROR")
    assert db_session.execute(select(func.count()).select_from(PinRow)).scalar_one() == 0


def test_create_pin_category_mismatch_after_match_is_validation_error(app_client, monkeypatch, db_session):
    """match_place가 다른 분류의 장소를 돌려줘도(방어) 핀을 만들지 않고 VALIDATION_ERROR."""
    from places import api as places_api
    from places.schemas import PlaceMatch

    monkeypatch.setattr(
        places_api, "match_place",
        lambda hint, *, db=None: PlaceMatch("p1", "x", 37.5, 127.0, "카페"),
    )
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"
    assert db_session.execute(select(func.count()).select_from(PinRow)).scalar_one() == 0


@pytest.mark.parametrize("source", ["coordinate", "link"])
def test_create_pin_coordinate_and_link_sources_are_422_validation_error(app_client, db_session, source):
    resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "source": source}, cookies=_auth())
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert db_session.execute(select(func.count()).select_from(PinRow)).scalar_one() == 0


def test_create_pin_rejects_link_url_with_422(app_client, db_session):
    """#148 — link_url을 보내면 422. 프론트가 그대로 보여줄 문장이 message다."""
    resp = app_client.post(
        "/maps/map_1/pins", json={**KALGUKSU, "link_url": "https://maps.google.com/?q=x"}, cookies=_auth()
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert resp.json()["message"] == "링크로는 핀을 찍을 수 없어요. 이름으로 검색해 주세요"
    assert db_session.execute(select(func.count()).select_from(PinRow)).scalar_one() == 0


@pytest.mark.parametrize("missing", ["place_id", "place_name", "lat", "lng"])
def test_create_pin_missing_hint_field_is_422(app_client, missing):
    body = {k: v for k, v in KALGUKSU.items() if k != missing}
    resp = app_client.post("/maps/map_1/pins", json=body, cookies=_auth())
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


def test_create_pin_includes_created_by_display_name_when_user_row_exists(app_client, db_session):
    ensure_users(db_session, "user_1", display_names={"user_1": "철수"})
    db_session.commit()

    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth("user_1"))
    assert resp.status_code == 201
    assert resp.json()["created_by_display_name"] == "철수"


def test_create_pin_without_cookie_is_401(app_client):
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_create_pin_non_member_is_404(app_client):
    """issue #61 — 비구성원이 핀을 생성할 수 있던 비대칭을 구조적으로 닫는다."""
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_create_pin_duplicate_place_is_409_with_existing_pin_id(app_client):
    """같은 지도에서 같은 places.id면 중복 — 카카오 ID가 달라도(같은 장소로 매칭되면) 막는다."""
    first = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    resp = app_client.post("/maps/map_1/pins", json={**KALGUKSU, "place_id": "kakao:2002"}, cookies=_auth("user_2"))
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "PIN_DUPLICATE"
    assert body["detail"]["pin_id"] == first.json()["id"]


def test_unique_index_is_per_map_and_place():
    index = next(i for i in PinRow.__table__.indexes if i.name == "uq_pins_map_place")
    assert [c.name for c in index.columns] == ["map_id", "place_id"]


def test_create_pin_reuses_place_after_soft_delete(app_client, db_session, fake_places):
    """부분 유니크가 deleted_at IS NULL 조건을 실제로 타는지 — 삭제된 자리엔 다시 찍을 수 있다."""
    _insert_pin(db_session, place_id=fake_places.place_id("seongsu-kalguksu"), deleted=True)
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
    assert resp.status_code == 201


def test_create_pin_recovers_from_real_db_constraint_violation(db_session, monkeypatch, fake_places):
    """사전조회(_find_existing_pin_id)가 놓친 경우(레이스)를 흉내내 실제 PostgreSQL 유니크
    제약 위반을 강제로 유발한다. begin_nested()만으로는 Session이 deactive 상태로 남아
    이후 쿼리가 PendingRollbackError로 죽는다는 걸 실측으로 확인한 회귀 테스트 —
    db.rollback()을 함께 불러야 여기서 실제로 복구된다(service.py::create_pin 참고)."""
    from authz.core import Principal
    from common.errors import AppError
    from pins import service
    from pins.schemas import PinCreateRequest

    existing = _insert_pin(db_session, place_id=fake_places.place_id("seongsu-kalguksu"))

    # 사전조회가 항상 "안 겹침"으로 보이게 만들어 실제 INSERT까지 가게 한다(레이스 재현).
    monkeypatch.setattr(service, "_find_existing_pin_id", lambda db, map_id, place_id: None)

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    req = PinCreateRequest(**KALGUKSU)

    try:
        service.create_pin(db_session, "map_1", principal, req)
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


def test_list_pins_keeps_checks_on_published_ai_pin(app_client, db_session):
    """가드레일 5 회귀 — 게시된 AI 핀의 조건별 충족 체크는 목록 조회에서도 유지된다(#57/#124).
    직접 생성한 핀(checks=None)은 반대로 응답에 checks 키 자체가 생략된다
    (response_model_exclude_none, 계약 그대로)."""
    checks = [
        {"fact_key": "is_open", "label": "영업 중", "passed": True, "confidence": "known", "needs_check": False},
    ]
    _insert_pin(db_session, kind="AI추천", place_id="checked_place", checks=checks)
    _insert_pin(db_session, kind="일반", place_id="unchecked_place")

    resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert resp.status_code == 200
    pins = resp.json()
    checked = next(p for p in pins if p["kind"] == "AI추천")
    unchecked = next(p for p in pins if p["kind"] == "일반")
    assert checked["checks"] == checks
    assert "checks" not in unchecked


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
    resp = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth())
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


def test_delete_pin_concurrent_double_delete_publishes_event_only_once(db_session):
    """#51 — 확인 후 처리(check-then-act, pin.deleted_at = ...; db.flush())였을 때는 동시
    삭제 요청 두 개가 둘 다 loader를 통과한 뒤(둘 다 deleted_at IS NULL을 봄) 둘 다 UPDATE에
    성공해 pin.deleted가 두 번 발행될 수 있었다. 서비스 함수를 같은 핀에 두 번 호출해
    (두 번째 호출 시점엔 이미 DB상 deleted_at이 채워져 있다 — 두 요청이 각자 로드는 먼저
    끝내고 나중에 순서대로 DB에 도달한 것과 동일한 조건) 조건부 UPDATE(WHERE deleted_at
    IS NULL) + rowcount 판단이 실제로 두 번째 호출을 막는지 확인한다."""
    from pins import service
    from pins.models import Pin as PinRow

    row = _insert_pin(db_session, created_by="user_1", place_id="race_delete")
    pin = db_session.get(PinRow, row.id)

    service.delete_pin(db_session, pin)  # 1번 요청 — 실제로 지운다, 이벤트 1건
    service.delete_pin(db_session, pin)  # 2번 요청(레이스) — rowcount=0, 이벤트 없음

    events = _events(db_session, type="pin.deleted")
    assert len(events) == 1


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
        json={"type": "against", "reason_chip_ids": ["food_spicy"]},
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
    assert events[0].payload == {
        "pin_id": str(row.id), "reaction_summary": {"like": 1, "neutral": 0, "against": 0},
        "user_id": "user_2", "display_name": "user_2", "type": "like",
    }


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


# --- GET /maps/{mapId}/counts (#141) ------------------------------------------------

def test_counts_fills_zero_for_empty_categories_and_kinds(app_client):
    resp = app_client.get("/maps/map_1/counts", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json() == {
        "members_with_opinion": 0, "members_total": 0,   # 이 파일은 FakeMembership이라 memberships 행이 없다
        "by_category": {"음식점": 0, "카페": 0, "숙소": 0, "관광지": 0, "기타": 0},
        "by_kind": {"일반": 0, "AI추천": 0, "확정": 0},
    }


def test_counts_counts_seeded_pins_by_category_and_kind(app_client, db_session):
    _insert_pin(db_session, category="음식점", kind="일반", place_id="c1")
    _insert_pin(db_session, category="음식점", kind="확정", place_id="c2", created_by="user_2")
    _insert_pin(db_session, category="카페", kind="AI추천", place_id="c3")
    _insert_pin(db_session, category="카페", kind="일반", place_id="c4", deleted=True)  # 삭제된 핀은 제외
    _insert_pin(db_session, category="음식점", kind="일반", place_id="c5", map_id="map_other")  # 다른 지도

    body = app_client.get("/maps/map_1/counts", cookies=_auth()).json()
    assert body["by_category"] == {"음식점": 2, "카페": 1, "숙소": 0, "관광지": 0, "기타": 0}
    assert body["by_kind"] == {"일반": 1, "AI추천": 1, "확정": 1}


def test_counts_excludes_other_users_private_pins_but_includes_own(app_client, db_session):
    """가드레일 1 — 남의 비공개 후보는 개수에도 새면 안 된다. 본인 것은 센다."""
    _insert_pin(db_session, kind="AI추천", visibility="private", created_by="stranger", place_id="p_other")
    _insert_pin(db_session, kind="AI추천", visibility="private", created_by="user_1", place_id="p_mine")
    _insert_pin(db_session, kind="일반", place_id="p_public", created_by="stranger")

    mine = app_client.get("/maps/map_1/counts", cookies=_auth("user_1")).json()
    assert mine["by_kind"] == {"일반": 1, "AI추천": 1, "확정": 0}

    theirs = app_client.get("/maps/map_1/counts", cookies=_auth("user_2")).json()
    assert theirs["by_kind"] == {"일반": 1, "AI추천": 0, "확정": 0}


def test_counts_matches_list_pins_visibility(app_client, db_session):
    _insert_pin(db_session, kind="AI추천", visibility="private", created_by="stranger", place_id="v1")
    _insert_pin(db_session, kind="일반", place_id="v2")
    _insert_pin(db_session, kind="AI추천", visibility="private", place_id="v3", created_by="user_1")
    listed = app_client.get("/maps/map_1/pins", cookies=_auth("user_1")).json()
    counted = app_client.get("/maps/map_1/counts", cookies=_auth("user_1")).json()
    assert sum(counted["by_kind"].values()) == len(listed)
    assert sum(counted["by_category"].values()) == len(listed)


def test_counts_non_member_is_404(app_client, db_session):
    _insert_pin(db_session, place_id="nm1")
    app.dependency_overrides[get_membership_gateway] = _deny_membership
    try:
        resp = app_client.get("/maps/map_1/counts", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_membership_gateway]
    assert resp.status_code == 404


def _like(db_session, pin_row, user_id):
    db_session.add(ReactionRow(pin_id=pin_row.id, user_id=user_id, type="like"))
    db_session.commit()


def test_list_liked_pins_excludes_other_users_private_pin(db_session):
    """가드레일 1 — 타인의 비공개 후보에 ♥가 있어도 요청자의 선호 프로필에 안 들어간다."""
    from pins import api as pins_api

    other_private = _insert_pin(db_session, created_by="user_2", visibility="private", place_id="lk_other_priv",
                                checks=[{"fact_key": "quiet"}])
    public = _insert_pin(db_session, created_by="user_2", visibility="public", place_id="lk_public")
    _like(db_session, other_private, "user_2")
    _like(db_session, public, "user_2")

    result = pins_api.list_liked_pins(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert len(result) == 1  # 공개 핀 하나뿐


def test_list_liked_pins_includes_own_private_pin(db_session):
    from pins import api as pins_api

    own_private = _insert_pin(db_session, created_by="user_1", visibility="private", place_id="lk_own_priv",
                              checks=[{"fact_key": "quiet"}])
    _like(db_session, own_private, "user_1")

    result = pins_api.list_liked_pins(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert result == [{"place_id": "lk_own_priv", "member_ids": {"user_1"}}]


def test_deleted_pin_reasons_still_reach_the_evidence_but_not_the_readiness_count(db_session):
    """#243 — 구성원 누구나 핀을 지울 수 있어서(#25), 지워진 핀에 남긴 알러지 사유가 근거에서 빠지면 안 된다(가드레일 8).
    준비 판정(몇 명이 반응했나)은 삭제 핀을 세지 않는다 — 사유(이력)와 현재 반응 수는 다른 질문이다."""
    from pins import api as pins_api

    gone = _insert_pin(db_session, place_id="rs_gone", deleted=True)
    alive = _insert_pin(db_session, place_id="rs_alive")
    db_session.add(ReactionRow(pin_id=gone.id, user_id="user_2", type="against", reason_text="조개 알러지"))
    db_session.add(ReactionRow(pin_id=alive.id, user_id="user_1", type="like"))
    db_session.commit()

    reasons = pins_api.list_reasoned_reactions(db_session, map_id="map_1", category="음식점")
    assert [(r["user_id"], r["reason_text"]) for r in reasons] == [("user_2", "조개 알러지")]
    assert pins_api.count_reacted_users(db_session, map_id="map_1", category="음식점") == 1

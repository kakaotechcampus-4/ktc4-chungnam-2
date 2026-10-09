"""
실제 PostgreSQL이 필요한 통합 테스트(conftest.py 참고, docker-compose up -d 전제).
POST /maps, GET /maps/{mapId}, GET /maps/{mapId}/members를 검증한다. 초대 발급·수락은
test_invites_api.py로 분리했다.

비구성원 응답은 404다(docs/CHANGELOG-api.md 2026-09-11) — conftest.py의 app_client가
authz.deps.get_membership_gateway를 maps.api.DbMembershipGateway로 실제 배선해서, 이
단언들이 AllowAllMembership 스텁 아래에서 무의미하게 통과하지 않는다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from auth.testing import ensure_users, session_cookie
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow


def _auth(user_id="user_1"):
    return session_cookie(user_id)


def _create_map(app_client, *, user_id="user_1", title="부산 여행", start="2026-10-10", end="2026-10-12"):
    resp = app_client.post(
        "/maps",
        json={"title": title, "start_date": start, "end_date": end},
        cookies=_auth(user_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_map_returns_201_with_owner_membership(app_client, db_session):
    body = _create_map(app_client)
    assert body["title"] == "부산 여행"
    assert body["start_date"] == "2026-10-10"
    assert body["end_date"] == "2026-10-12"
    assert body["member_count"] == 1
    assert body["confirmed_count"] == 0  # 방금 만든 지도라 확정 리스트가 비어 있다(항목 5 해결)

    row = db_session.execute(
        select(MembershipRow).where(MembershipRow.map_id == body["id"], MembershipRow.user_id == "user_1")
    ).scalar_one()
    assert row.role == "owner"


def test_create_map_end_date_before_start_date_is_422(app_client):
    resp = app_client.post(
        "/maps",
        json={"title": "잘못된 여행", "start_date": "2026-10-12", "end_date": "2026-10-10"},
        cookies=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_map_missing_title_is_422(app_client):
    resp = app_client.post(
        "/maps", json={"start_date": "2026-10-10", "end_date": "2026-10-12"}, cookies=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_map_without_cookie_is_401(app_client):
    resp = app_client.post(
        "/maps", json={"title": "x", "start_date": "2026-10-10", "end_date": "2026-10-12"},
    )
    assert resp.status_code == 401


def test_get_map_as_non_member_is_404(app_client):
    body = _create_map(app_client, user_id="user_1")
    resp = app_client.get(f"/maps/{body['id']}", cookies=_auth("user_2"))
    assert resp.status_code == 404
    assert "부산" not in resp.text  # 존재 자체를 흘리지 않는다


def test_get_unknown_map_is_404(app_client):
    resp = app_client.get("/maps/does-not-exist", cookies=_auth("user_1"))
    assert resp.status_code == 404


def test_get_map_member_count_reflects_joined_members(app_client):
    body = _create_map(app_client, user_id="user_1")
    map_id = body["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()
    app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))

    resp = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1"))
    assert resp.json()["member_count"] == 2


def test_list_members_returns_only_honest_fields(app_client):
    body = _create_map(app_client, user_id="user_1")
    map_id = body["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()
    app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))

    resp = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1"))
    assert resp.status_code == 200
    members = resp.json()
    assert {m["user_id"] for m in members} == {"user_1", "user_2"}
    # online을 채울 데이터 출처가 없다 — 응답에 키 자체가 없어야 한다
    # (False로 채우는 거짓 fallback을 만들지 않았다는 증거). display_name은 users 행에서 온다.
    for m in members:
        assert set(m.keys()) == {"user_id", "role", "display_name"}


def test_list_members_marks_creator_as_owner_and_joiner_as_member(app_client):
    map_id = _create_map(app_client, user_id="user_1")["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()
    app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))

    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_2")).json()
    assert {m["user_id"]: m["role"] for m in members} == {"user_1": "owner", "user_2": "member"}


def test_list_members_includes_display_name_when_user_row_exists(app_client, db_session):
    """auth.api.display_names 배선(maps/for_Root.md 항목 5 해결) 회귀 테스트 — 실제 users
    행이 있으면 display_name이 채워져야 한다(인증이 users 행을 요구하므로(#126)
    행이 없는 구성원은 탈퇴 등으로 행이 사라진 경우뿐이다)."""
    ensure_users(db_session, "user_1", display_names={"user_1": "철수"})
    db_session.commit()

    body = _create_map(app_client, user_id="user_1")

    resp = app_client.get(f"/maps/{body['id']}/members", cookies=_auth("user_1"))
    assert resp.status_code == 200
    members = resp.json()
    assert members == [{"user_id": "user_1", "role": "owner", "display_name": "철수"}]


def test_list_members_as_non_member_is_404(app_client):
    body = _create_map(app_client, user_id="user_1")
    resp = app_client.get(f"/maps/{body['id']}/members", cookies=_auth("user_2"))
    assert resp.status_code == 404


def test_create_map_without_region_omits_region_key(app_client):
    """region 없이 생성하는 기존 동작은 회귀 없이 그대로 — 키 자체가 없어야 한다."""
    body = _create_map(app_client)
    assert "region" not in body


def test_create_map_with_region_round_trips(app_client):
    resp = app_client.post(
        "/maps",
        json={
            "title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12",
            "region": {"label": "부산", "lat": 35.1, "lng": 129.0},
        },
        cookies=_auth(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["region"] == {"label": "부산", "lat": pytest.approx(35.1), "lng": pytest.approx(129.0)}


def test_create_map_with_invalid_region_lat_is_422(app_client):
    resp = app_client.post(
        "/maps",
        json={
            "title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12",
            "region": {"label": "부산", "lat": 200, "lng": 129.0},
        },
        cookies=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_get_map_with_region_round_trips(app_client):
    """POST 응답뿐 아니라 GET /maps/{mapId}로 다시 조회해도 region이 유지된다 — DB 왕복 확인."""
    created = app_client.post(
        "/maps",
        json={
            "title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12",
            "region": {"label": "부산", "lat": 35.1, "lng": 129.0},
        },
        cookies=_auth(),
    ).json()

    resp = app_client.get(f"/maps/{created['id']}", cookies=_auth())
    assert resp.status_code == 200
    assert resp.json()["region"] == {"label": "부산", "lat": pytest.approx(35.1), "lng": pytest.approx(129.0)}


def test_list_maps_without_membership_is_empty(app_client):
    resp = app_client.get("/maps", cookies=_auth("user_lonely"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_maps_without_cookie_is_401(app_client):
    resp = app_client.get("/maps")
    assert resp.status_code == 401


def test_list_maps_returns_only_my_maps_most_recent_first(app_client, db_session):
    """created_at은 이 테스트 픽스처의 트랜잭션 안에서 Postgres now()(트랜잭션 시작 시각 고정)로
    채워져 두 map이 같은 값을 가질 수 있다 — 순서를 실제로 검증하려면 직접 벌려놓아야 한다."""
    first = _create_map(app_client, user_id="user_1", title="첫 여행")
    second = _create_map(app_client, user_id="user_1", title="둘째 여행")
    _create_map(app_client, user_id="user_2", title="남의 여행")  # 목록에 섞이면 안 된다

    now = datetime.now(timezone.utc)
    db_session.execute(
        update(MapRow).where(MapRow.id == first["id"]).values(created_at=now - timedelta(hours=1))
    )
    db_session.execute(update(MapRow).where(MapRow.id == second["id"]).values(created_at=now))
    db_session.flush()

    resp = app_client.get("/maps", cookies=_auth("user_1"))
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == [second["id"], first["id"]]


def test_list_maps_member_count_has_no_n_plus_one(app_client):
    """GET /maps에서 지도별 member_count가 정확해야 한다 — 한 번의 집계 쿼리로 채워도 값이
    틀리면 의미가 없다(service.py::_member_counts의 GROUP BY 정확성 회귀 테스트)."""
    map_a = _create_map(app_client, user_id="user_1", title="A")
    map_b = _create_map(app_client, user_id="user_1", title="B")

    invite = app_client.post(f"/maps/{map_a['id']}/invite", cookies=_auth("user_1")).json()
    app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))

    resp = app_client.get("/maps", cookies=_auth("user_1"))
    body = {m["id"]: m for m in resp.json()}
    assert body[map_a["id"]]["member_count"] == 2
    assert body[map_b["id"]]["member_count"] == 1


def test_list_maps_includes_region_when_present(app_client):
    with_region = app_client.post(
        "/maps",
        json={
            "title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12",
            "region": {"label": "부산", "lat": 35.1, "lng": 129.0},
        },
        cookies=_auth(),
    ).json()
    without_region = _create_map(app_client, title="지역 없는 여행")

    body = {m["id"]: m for m in app_client.get("/maps", cookies=_auth()).json()}
    assert body[with_region["id"]]["region"] == {
        "label": "부산", "lat": pytest.approx(35.1), "lng": pytest.approx(129.0)
    }
    assert "region" not in body[without_region["id"]]


# --- #244 입력 길이 제한 / #245 탈퇴한 구성원 수 ---


def _create_body(**overrides):
    body = {"title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12"}
    body.update(overrides)
    return body


def test_title_and_region_label_accept_exactly_100_chars(app_client):
    resp = app_client.post(
        "/maps",
        json=_create_body(title="가" * 100, region={"label": "나" * 100, "lat": 35.1, "lng": 129.0}),
        cookies=_auth("user_1"),
    )
    assert resp.status_code == 201, resp.text


def test_title_over_100_chars_is_422(app_client):
    resp = app_client.post("/maps", json=_create_body(title="가" * 101), cookies=_auth("user_1"))
    assert resp.status_code == 422


def test_region_label_over_100_chars_is_422(app_client):
    resp = app_client.post(
        "/maps",
        json=_create_body(region={"label": "나" * 101, "lat": 35.1, "lng": 129.0}),
        cookies=_auth("user_1"),
    )
    assert resp.status_code == 422


def test_empty_title_is_still_422(app_client):
    resp = app_client.post("/maps", json=_create_body(title=""), cookies=_auth("user_1"))
    assert resp.status_code == 422


def _join(app_client, map_id, user_id):
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()
    assert app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth(user_id)).status_code == 200


def _withdraw(db_session, user_id):
    from datetime import datetime, timezone

    from sqlalchemy import update

    from auth.models import User

    db_session.execute(update(User).where(User.id == user_id).values(deleted_at=datetime.now(timezone.utc)))
    db_session.commit()


def test_withdrawn_member_is_excluded_from_member_count_and_members(app_client, db_session):
    from maps.api import count_members

    map_id = app_client.post("/maps", json=_create_body(), cookies=_auth("user_1")).json()["id"]
    _join(app_client, map_id, "user_2")
    _withdraw(db_session, "user_2")

    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["member_count"] == 1
    listed = app_client.get("/maps", cookies=_auth("user_1")).json()
    assert [m["member_count"] for m in listed if m["id"] == map_id] == [1]
    assert count_members(db_session, map_id) == 1
    # 구성원 목록도 탈퇴자를 뺀다(#439) — 길이가 member_count와 같다
    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_1")).json()
    assert [m["user_id"] for m in members] == ["user_1"]
    assert len(members) == app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["member_count"]

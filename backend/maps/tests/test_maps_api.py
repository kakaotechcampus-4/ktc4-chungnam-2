"""
실제 PostgreSQL이 필요한 통합 테스트(conftest.py 참고, docker-compose up -d 전제).
POST /maps, GET /maps/{mapId}, GET /maps/{mapId}/members를 검증한다. 초대 발급·수락은
test_invites_api.py로 분리했다.

비구성원 응답은 404다(docs/CHANGELOG-api.md 2026-09-11) — conftest.py의 app_client가
authz.deps.get_membership_gateway를 maps.api.DbMembershipGateway로 실제 배선해서, 이
단언들이 AllowAllMembership 스텁 아래에서 무의미하게 통과하지 않는다.
"""

from sqlalchemy import select

from maps.models import Membership as MembershipRow


def _auth(user_id="user_1"):
    return {"session": user_id}


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
    # display_name·online을 채울 데이터 출처가 없다 — 응답에 키 자체가 없어야 한다
    # (user_id로 대체하거나 False로 채우는 거짓 fallback을 만들지 않았다는 증거).
    for m in members:
        assert set(m.keys()) == {"user_id"}


def test_list_members_includes_display_name_when_user_row_exists(app_client, db_session):
    """auth.api.display_names 배선(maps/for_Root.md 항목 5 해결) 회귀 테스트 — 실제 users
    행이 있으면 display_name이 채워져야 한다(위 test_list_members_returns_only_honest_fields는
    users 행이 없는 dev 세션 쿠키 케이스라 생략되는 게 여전히 맞다)."""
    from auth.models import User

    db_session.add(User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수"))
    db_session.commit()

    body = _create_map(app_client, user_id="user_1")

    resp = app_client.get(f"/maps/{body['id']}/members", cookies=_auth("user_1"))
    assert resp.status_code == 200
    members = resp.json()
    assert members == [{"user_id": "user_1", "display_name": "철수"}]


def test_list_members_as_non_member_is_404(app_client):
    body = _create_map(app_client, user_id="user_1")
    resp = app_client.get(f"/maps/{body['id']}/members", cookies=_auth("user_2"))
    assert resp.status_code == 404

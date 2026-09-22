"""
POST /maps/{mapId}/invite, POST /invites/{token}/accept 통합 테스트(conftest.py 참고).
동시성/멱등성 설계(maps/service.py::accept_invite)의 핵심 불변식을 고정한다 —
"두 번 수락해도 상태가 한 번만 변한다", "owner가 자기 초대를 열어도 강등되지 않는다",
"검사가 INSERT보다 먼저다".
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from common.events import EventLog
from maps.models import Invite as InviteRow
from maps.models import Membership as MembershipRow


def _auth(user_id="user_1"):
    return {"session": user_id}


def _create_map(app_client, *, user_id="user_1"):
    resp = app_client.post(
        "/maps",
        json={"title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12"},
        cookies=_auth(user_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _member_count(db_session, map_id):
    return db_session.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id)
    ).scalars().all()


def _events(db_session, *, map_id, type=None):
    query = select(EventLog).where(EventLog.map_id == map_id)
    if type is not None:
        query = query.where(EventLog.type == type)
    return db_session.execute(query).scalars().all()


def test_create_invite_returns_201_with_working_token(app_client, db_session):
    map_body = _create_map(app_client)
    resp = app_client.post(f"/maps/{map_body['id']}/invite", cookies=_auth("user_1"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["token"]) >= 32
    assert body["url"].endswith(f"/invites/{body['token']}")

    # Python 3.10의 fromisoformat은 "Z" 접미사를 못 읽는다(3.11부터 지원) — FastAPI/pydantic이
    # datetime을 "...Z"로 직렬화하므로 파싱 전에 치환한다.
    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires_at > datetime.now(timezone.utc)

    row = db_session.execute(select(InviteRow).where(InviteRow.token == body["token"])).scalar_one()
    assert row.used_count == 0


def test_create_invite_twice_gives_distinct_tokens(app_client):
    map_body = _create_map(app_client)
    first = app_client.post(f"/maps/{map_body['id']}/invite", cookies=_auth("user_1")).json()
    second = app_client.post(f"/maps/{map_body['id']}/invite", cookies=_auth("user_1")).json()
    assert first["token"] != second["token"]


def test_create_invite_as_non_member_is_404(app_client):
    map_body = _create_map(app_client, user_id="user_1")
    resp = app_client.post(f"/maps/{map_body['id']}/invite", cookies=_auth("user_2"))
    assert resp.status_code == 404


def test_accept_invite_adds_member_and_emits_event(app_client, db_session):
    map_body = _create_map(app_client, user_id="user_1")
    map_id = map_body["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()

    resp = app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["member_count"] == 2

    membership = db_session.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2")
    ).scalar_one()
    assert membership.role == "member"

    invite_row = db_session.execute(select(InviteRow).where(InviteRow.token == invite["token"])).scalar_one()
    assert invite_row.used_count == 1

    events = _events(db_session, map_id=map_id, type="member.joined")
    assert len(events) == 1
    assert events[0].channel == "public"
    assert events[0].recipient_user_id is None
    assert events[0].payload == {"user_id": "user_2"}


def test_accept_invite_twice_is_idempotent(app_client, db_session):
    map_body = _create_map(app_client, user_id="user_1")
    map_id = map_body["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()

    first = app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))
    second = app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["member_count"] == 2  # 두 번째 수락으로 늘지 않는다

    invite_row = db_session.execute(select(InviteRow).where(InviteRow.token == invite["token"])).scalar_one()
    assert invite_row.used_count == 1  # 실제 가입 1회분만 반영

    events = _events(db_session, map_id=map_id, type="member.joined")
    assert len(events) == 1  # 재수락으로 이벤트가 추가 발행되지 않는다


def test_owner_accepting_own_invite_does_not_demote_role(app_client, db_session):
    """ON CONFLICT DO NOTHING을 쓰는 이유 — DO UPDATE였다면 owner가 자기 초대 링크를 열 때
    role이 'member'로 조용히 강등된다."""
    map_body = _create_map(app_client, user_id="user_1")
    map_id = map_body["id"]
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()

    resp = app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_1"))
    assert resp.status_code == 200
    assert resp.json()["member_count"] == 1

    membership = db_session.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_1")
    ).scalar_one()
    assert membership.role == "owner"

    invite_row = db_session.execute(select(InviteRow).where(InviteRow.token == invite["token"])).scalar_one()
    assert invite_row.used_count == 0
    assert len(_events(db_session, map_id=map_id, type="member.joined")) == 0


def test_accept_unknown_token_is_401_and_creates_no_membership(app_client, db_session):
    resp = app_client.post("/invites/does-not-exist/accept", cookies=_auth("user_1"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_accept_expired_token_is_401_and_creates_no_membership(app_client, db_session):
    map_body = _create_map(app_client, user_id="user_1")
    map_id = map_body["id"]

    expired = InviteRow(
        token="expired-token-1234567890",
        map_id=map_id,
        created_by="user_1",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(expired)
    db_session.commit()

    before = _member_count(db_session, map_id)
    resp = app_client.post("/invites/expired-token-1234567890/accept", cookies=_auth("user_2"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"

    after = _member_count(db_session, map_id)
    assert len(after) == len(before)  # 검사가 INSERT보다 먼저 — 멤버십이 추가되지 않았다


def test_accept_invite_without_cookie_is_401(app_client):
    map_body = _create_map(app_client, user_id="user_1")
    invite = app_client.post(f"/maps/{map_body['id']}/invite", cookies=_auth("user_1")).json()

    resp = app_client.post(f"/invites/{invite['token']}/accept")
    assert resp.status_code == 401

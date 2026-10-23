"""
POST /auth/guest (#472) — 로그인 전에 이름만으로 초대받은 지도에 들어간다. 모듈 사이 이음새(auth → maps.api,
notifications, 탈퇴 연쇄)라 여기서 검증한다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from auth import api as auth_api
from auth import router as auth_router
from auth import service as auth_service
from auth.models import User, UserIdentity
from auth.testing import create_kakao_user, session_cookie
from common.errors import AppError
from common.events import EventLog
from maps import api as maps_api
from maps.models import Invite as InviteRow
from maps.models import Membership as MembershipRow
from notifications.models import Notification


@pytest.fixture(autouse=True)
def _fresh_limiter():
    auth_router.guest_join_limiter._hits.clear()
    yield
    auth_router.guest_join_limiter._hits.clear()


@pytest.fixture()
def owner(app_client, two_users):
    return TestClient(app_client.app, cookies=session_cookie("user_a"))


@pytest.fixture()
def anon(app_client):
    return TestClient(app_client.app)


def _invite(owner):
    map_id = owner.post("/maps", json={"title": "부산", "start_date": "2026-11-01", "end_date": "2026-11-03"}).json()["id"]
    return map_id, owner.post(f"/maps/{map_id}/invite").json()["token"]


def _join(client, token, name="  손님  "):
    return client.post("/auth/guest", json={"display_name": name, "invite_token": token})


def test_guest_join_creates_account_joins_map_and_sets_session(owner, anon, db_session):
    map_id, token = _invite(owner)

    resp = _join(anon, token)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["display_name"] == "손님"          # 앞뒤 공백 제거
    assert body["user"]["is_guest"] is True
    assert body["map"]["id"] == map_id
    assert body["map"]["member_count"] == 2
    cookie = resp.headers["set-cookie"]
    assert "httponly" in cookie.lower()
    assert "Max-Age=2592000" in cookie   # 30일

    row = db_session.get(User, body["user"]["id"])
    assert (row.is_guest, row.guest_invite_token) == (True, token)
    assert db_session.query(UserIdentity).filter_by(user_id=row.id).count() == 0   # 게스트는 로그인 수단이 없다(#694)
    assert row.last_seen_at is not None
    assert db_session.query(InviteRow).filter_by(token=token).one().used_count == 1
    assert db_session.query(EventLog).filter_by(map_id=map_id, type="member.joined").count() == 1
    assert db_session.query(Notification).filter_by(user_id="user_a", type="member_joined").count() == 1

    # 받은 쿠키로 그대로 로그인 상태가 되고, 그 지도를 볼 수 있다
    me = anon.get("/auth/me")
    assert me.status_code == 200 and me.json()["is_guest"] is True
    assert anon.get(f"/maps/{map_id}").status_code == 200
    assert auth_api.guest_user_ids(db_session, [body["user"]["id"], "user_a"]) == {body["user"]["id"]}


@pytest.mark.parametrize("name", ["", "   ", "가" * 51])
def test_invalid_name_is_422(owner, anon, name):
    _, token = _invite(owner)
    assert _join(anon, token, name).status_code == 422


def test_unknown_token_is_404_and_creates_no_account(anon, db_session):
    before = db_session.query(User).count()
    resp = _join(anon, "no-such-token")
    assert resp.status_code == 404 and resp.json()["code"] == "INVITE_NOT_FOUND"
    assert db_session.query(User).count() == before


def test_expired_and_revoked_tokens_are_410(owner, anon, db_session):
    _, token = _invite(owner)
    db_session.query(InviteRow).filter_by(token=token).one().expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.flush()
    resp = _join(anon, token)
    assert resp.status_code == 410 and resp.json()["code"] == "INVITE_EXPIRED"

    _, token2 = _invite(owner)
    assert owner.delete(f"/invites/{token2}").status_code == 204
    resp = _join(anon, token2)
    assert resp.status_code == 410 and resp.json()["code"] == "INVITE_REVOKED"


def test_eleventh_guest_for_one_token_is_409_but_another_token_is_fine(owner, anon, db_session):
    _, token = _invite(owner)
    for _ in range(10):
        assert _join(anon, token).status_code == 201
        auth_router.guest_join_limiter._hits.clear()   # 이 테스트는 IP 상한이 아니라 토큰별 한도를 본다
    before = db_session.query(User).count()

    resp = _join(anon, token)

    assert resp.status_code == 409 and resp.json()["code"] == "GUEST_LIMIT"
    assert db_session.query(User).count() == before
    _, other = _invite(owner)
    assert _join(anon, other).status_code == 201


def _claim(db_session, guest_id, kakao_id):
    """게스트에 처음 쓰는 카카오 수단을 붙인다(콜백의 처음 전환과 같은 함수)."""
    user, merged = auth_service.claim_guest(
        db_session, guest_user_id=guest_id, provider="kakao", provider_user_id=kakao_id, display_name="카카오 이름",
    )
    assert (user.id, merged) == (guest_id, True)


def test_guest_who_attached_kakao_no_longer_counts_toward_the_invite_limit(owner, anon, db_session):
    """카카오 수단을 붙이면 guest_invite_token을 비우고 게스트도 아니다 — 초대당 10명에서 빠진다(#694)."""
    _, token = _invite(owner)
    ids = []
    for _ in range(10):
        ids.append(_join(anon, token).json()["user"]["id"])
        auth_router.guest_join_limiter._hits.clear()
    assert _join(anon, token).status_code == 409
    auth_router.guest_join_limiter._hits.clear()

    _claim(db_session, ids[0], "k-limit")

    assert db_session.get(User, ids[0]).guest_invite_token is None
    assert _join(anon, token).status_code == 201


def test_duplicate_display_names_are_allowed(owner, anon):
    _, token = _invite(owner)
    ids = {_join(anon, token, "손님").json()["user"]["id"] for _ in range(2)}
    assert len(ids) == 2


def test_rate_limit_per_ip_counts_failures_too_and_is_429(anon):
    for _ in range(auth_router.GUEST_JOIN_PER_HOUR):
        assert _join(anon, "no-such-token").status_code == 404
    resp = _join(anon, "no-such-token")
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"


def test_last_seen_is_refreshed_at_most_once_a_day(owner, anon, db_session):
    _, token = _invite(owner)
    row = db_session.get(User, _join(anon, token).json()["user"]["id"])

    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    row.last_seen_at = recent
    db_session.flush()
    anon.get("/auth/me")
    assert row.last_seen_at == recent                      # 하루 안이면 그대로

    stale = datetime.now(timezone.utc) - timedelta(days=2)
    row.last_seen_at = stale
    db_session.flush()
    anon.get("/auth/me")
    assert row.last_seen_at > stale + timedelta(days=1)    # 이틀 지났으니 갱신


def test_purge_inactive_guests_uses_withdraw_rules(owner, anon, db_session):
    _, token = _invite(owner)
    old_id = _join(anon, token).json()["user"]["id"]
    fresh_id = _join(TestClient(anon.app), token).json()["user"]["id"]
    now = datetime.now(timezone.utc)
    db_session.get(User, old_id).last_seen_at = now - timedelta(days=91)
    db_session.get(User, fresh_id).last_seen_at = now - timedelta(days=89)
    claimed_id = _join(TestClient(anon.app), token).json()["user"]["id"]
    _claim(db_session, claimed_id, "k-purge")
    db_session.get(User, claimed_id).last_seen_at = now - timedelta(days=91)   # 카카오 수단이 있으면 게스트 정리 대상이 아니다
    db_session.flush()

    assert auth_api.purge_inactive_guests(db_session, now) == 1

    assert db_session.get(User, old_id).deleted_at is not None
    assert db_session.get(User, fresh_id).deleted_at is None
    assert db_session.get(User, claimed_id).deleted_at is None
    assert db_session.get(User, "user_a").deleted_at is None            # 일반 사용자는 건드리지 않는다
    assert auth_api.display_names(db_session, [old_id]) == {old_id: "탈퇴한 구성원"}
    assert auth_api.purge_inactive_guests(db_session, now) == 0          # 두 번째는 건너뜀


def test_withdrawn_guest_goes_through_the_normal_withdraw_cascade(owner, anon, db_session):
    map_id, token = _invite(owner)
    guest_id = _join(anon, token).json()["user"]["id"]
    db_session.add(Notification(user_id=guest_id, type="member_joined", map_id=map_id, message="m"))
    db_session.flush()

    assert anon.post("/auth/withdraw").status_code == 204

    assert db_session.get(User, guest_id).deleted_at is not None
    assert db_session.query(Notification).filter_by(user_id=guest_id).count() == 0   # delete_by_user 연쇄에 포함
    assert db_session.query(MembershipRow).filter_by(map_id=map_id, user_id=guest_id).count() == 1   # 멤버십은 남는다(#245)
    assert anon.get("/auth/me").status_code == 401


def test_maps_api_check_invite_raises_what_accept_raises(owner, db_session):
    _, token = _invite(owner)
    maps_api.check_invite(db_session, token)   # 정상 토큰은 조용히 통과

    with pytest.raises(AppError) as unknown:
        maps_api.check_invite(db_session, "nope")
    assert unknown.value.code == "INVITE_NOT_FOUND"

    db_session.query(InviteRow).filter_by(token=token).one().revoked_at = datetime.now(timezone.utc)
    db_session.flush()
    with pytest.raises(AppError) as revoked:
        maps_api.check_invite(db_session, token)
    assert revoked.value.code == "INVITE_REVOKED"


def test_maps_api_accept_invite_joins_and_emits_event(owner, db_session):
    map_id, token = _invite(owner)
    create_kakao_user(db_session, "late", provider_user_id="pl", display_name="늦게")

    result = maps_api.accept_invite(db_session, token=token, user_id="late")

    assert result.id == map_id and result.member_count == 2
    assert db_session.query(EventLog).filter_by(map_id=map_id, type="member.joined").count() == 1

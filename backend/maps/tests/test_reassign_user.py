"""api.reassign_user(#560) — 게스트 멤버십·초대 발급자를 카카오 계정으로 옮긴다."""

from datetime import datetime, timezone

from maps import api
from maps.models import Invite, Map, Membership

GUEST, KAKAO = "guest_1", "kakao_1"


def _map(db, members: dict[str, str]):
    row = Map(title="지도", start_date=datetime(2026, 10, 1).date(), end_date=datetime(2026, 10, 2).date(),
              created_by="x")
    db.add(row)
    db.flush()
    for user_id, role in members.items():
        db.add(Membership(map_id=row.id, user_id=user_id, role=role))
    db.flush()
    return row.id


def _members(db, map_id):
    return {m.user_id: m.role for m in db.query(Membership).filter_by(map_id=map_id)}


def test_moves_membership_and_invites(db_session):
    mid = _map(db_session, {"owner_1": "owner", GUEST: "member"})
    db_session.add(Invite(token="t1", map_id=mid, created_by=GUEST, expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    db_session.flush()

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result == {"memberships": 1, "memberships_dropped": 0, "invites": 1}
    assert _members(db_session, mid) == {"owner_1": "owner", KAKAO: "member"}
    assert db_session.get(Invite, "t1").created_by == KAKAO


def test_conflict_keeps_kakao_role_and_drops_guest_row(db_session):
    mid = _map(db_session, {KAKAO: "owner", GUEST: "member"})
    other = _map(db_session, {"owner_1": "owner", GUEST: "member"})

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["memberships"] == 1 and result["memberships_dropped"] == 1
    assert _members(db_session, mid) == {KAKAO: "owner"}
    assert _members(db_session, other) == {"owner_1": "owner", KAKAO: "member"}
    assert api.count_members(db_session, mid) == 1


def test_ignores_map_limit(db_session):
    ids = [_map(db_session, {"owner_1": "owner", GUEST: "member"}) for _ in range(3)]
    for _ in range(20):
        _map(db_session, {"o": "owner", KAKAO: "member"})

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["memberships"] == 3
    assert all(KAKAO in _members(db_session, i) for i in ids)


def test_idempotent_and_same_id_noop(db_session):
    mid = _map(db_session, {"owner_1": "owner", GUEST: "member"})

    assert api.reassign_user(db_session, from_user_id=GUEST, to_user_id=GUEST) == {
        "memberships": 0, "memberships_dropped": 0, "invites": 0}
    assert GUEST in _members(db_session, mid)

    api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)
    again = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert again == {"memberships": 0, "memberships_dropped": 0, "invites": 0}
    assert _members(db_session, mid) == {"owner_1": "owner", KAKAO: "member"}

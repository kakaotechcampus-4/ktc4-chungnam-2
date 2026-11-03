"""#1013 — GET /maps/{mapId}/trash: 내가 되살릴 수 있는 지운 핀만, 30일 안, 최근 삭제순."""

from datetime import datetime, timedelta, timezone

import authz.deps
from authz.testing import FakeMembership
from main import app
from pins.tests.test_pins_api import _auth, _insert_pin


def _roles(**roles):
    """app_client의 기본 멤버십은 모두 member다 — 방장이 필요한 테스트는 이걸로 바꾼다."""
    app.dependency_overrides[authz.deps.get_membership_gateway] = lambda: FakeMembership(
        {tuple(key.split("__")): role for key, role in roles.items()}
    )


def _trashed(db_session, *, days_ago: float, created_by="user_1", deleted_by="user_1", confirmed=False, map_id="map_1"):
    row = _insert_pin(db_session, created_by=created_by, map_id=map_id)
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    row.deleted_by = deleted_by
    row.deleted_was_confirmed = confirmed
    db_session.commit()
    return row


def _get(app_client, user="user_1", map_id="map_1"):
    return app_client.get(f"/maps/{map_id}/trash", cookies=_auth(user))


def test_owner_sees_every_trashed_pin_most_recent_first(app_client, db_session):
    _roles(map_1__user_1="owner", map_1__user_2="member")
    older = _trashed(db_session, days_ago=5, created_by="user_2", deleted_by="user_2")
    newer = _trashed(db_session, days_ago=1, created_by="user_1", confirmed=True)
    body = _get(app_client).json()
    assert body["retention_days"] == 30
    assert [i["pin"]["id"] for i in body["items"]] == [str(newer.id), str(older.id)]
    first = body["items"][0]
    assert first["was_confirmed"] is True and first["days_left"] == 29
    assert first["purge_at"] > first["deleted_at"]


def test_member_sees_only_their_own_pins(app_client, db_session):
    mine = _trashed(db_session, days_ago=2, created_by="user_2", deleted_by="user_2")
    _trashed(db_session, days_ago=1, created_by="user_1")
    ids = [i["pin"]["id"] for i in _get(app_client, "user_2").json()["items"]]
    assert ids == [str(mine.id)]


def test_pins_past_thirty_days_and_live_pins_are_not_listed(app_client, db_session):
    _trashed(db_session, days_ago=30.1)
    kept = _trashed(db_session, days_ago=29)
    _insert_pin(db_session)   # 지우지 않은 핀
    ids = [i["pin"]["id"] for i in _get(app_client).json()["items"]]
    assert ids == [str(kept.id)]


def test_trash_is_per_map_and_non_member_is_404(app_client, db_session):
    _roles(map_1__user_1="owner", map_2__user_1="owner")
    _trashed(db_session, days_ago=1, map_id="map_2")
    assert _get(app_client, "user_1", "map_1").json()["items"] == []
    assert len(_get(app_client, "user_1", "map_2").json()["items"]) == 1
    assert _get(app_client, "user_1", "map_9").status_code == 404


def test_empty_trash_is_an_empty_list(app_client):
    assert _get(app_client).json() == {"items": [], "retention_days": 30}


def test_equal_deleted_at_is_ordered_by_id_descending(app_client, db_session):
    at = datetime.now(timezone.utc) - timedelta(days=3)
    rows = [_trashed(db_session, days_ago=3) for _ in range(3)]
    for r in rows:
        r.deleted_at = at
    db_session.commit()
    ids = [i["pin"]["id"] for i in _get(app_client).json()["items"]]
    assert ids == sorted((str(r.id) for r in rows), reverse=True)


def test_thirty_day_boundary_matches_restore_and_purge(app_client, db_session):
    from pins import core
    inside = _trashed(db_session, days_ago=0)
    outside = _trashed(db_session, days_ago=0)
    inside.deleted_at = datetime.now(timezone.utc) - timedelta(days=30) + timedelta(minutes=1)   # 29일 23시간 59분 전
    outside.deleted_at = datetime.now(timezone.utc) - timedelta(days=30) - timedelta(seconds=1)  # 30일이 막 지났다
    db_session.commit()
    items = _get(app_client).json()["items"]
    assert [i["pin"]["id"] for i in items] == [str(inside.id)]
    assert items[0]["days_left"] == 1
    assert core.is_restorable(inside.deleted_at, datetime.now(timezone.utc))
    assert not core.is_restorable(outside.deleted_at, datetime.now(timezone.utc))


def _real_membership(db_session):
    from maps import api as maps_api
    app.dependency_overrides[authz.deps.get_membership_gateway] = lambda: maps_api.DbMembershipGateway(db_session)


def test_deleted_map_trash_is_404_with_real_membership(app_client, db_session):
    from auth.testing import ensure_users
    from maps.models import Map as MapRow
    from pins.tests.test_author_display_369 import _make_map
    ensure_users(db_session, "user_1")
    _make_map(db_session, "map_1", {"user_1": "owner"})
    _trashed(db_session, days_ago=1)
    _real_membership(db_session)
    assert _get(app_client).status_code == 200
    db_session.get(MapRow, "map_1").deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    assert _get(app_client).status_code == 404


def test_left_and_withdrawn_deleters_get_the_contract_names(app_client, db_session):
    from auth.testing import ensure_users
    from pins.tests.test_author_display_369 import _leave, _make_map, _withdraw
    ensure_users(db_session, "user_1", "user_2", "user_3",
                 display_names={"user_1": "철수", "user_2": "영희", "user_3": "민수"})
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member", "user_3": "member"})
    left = _trashed(db_session, days_ago=1, created_by="user_2", deleted_by="user_2")
    gone = _trashed(db_session, days_ago=2, created_by="user_3", deleted_by="user_3")
    named = _trashed(db_session, days_ago=3, created_by="user_1", deleted_by="user_1")
    _leave(db_session, "map_1", "user_2")
    _withdraw(db_session, "user_3")      # 탈퇴자 멤버십 행은 남는다(#245)
    _real_membership(db_session)
    names = {i["pin"]["id"]: i["deleted_by_name"] for i in _get(app_client).json()["items"]}
    assert names == {str(left.id): "나간 구성원", str(gone.id): "탈퇴한 구성원", str(named.id): "철수"}


def test_guest_member_sees_only_their_own_trashed_pins(app_client, db_session):
    from auth.models import User
    from auth.testing import ensure_users
    from pins.tests.test_author_display_369 import _make_map
    ensure_users(db_session, "user_1", "user_2")
    db_session.get(User, "user_2").is_guest = True
    db_session.commit()
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member"})
    _trashed(db_session, days_ago=1, created_by="user_1")
    mine = _trashed(db_session, days_ago=2, created_by="user_2", deleted_by="user_2")
    _real_membership(db_session)
    assert [i["pin"]["id"] for i in _get(app_client, "user_2").json()["items"]] == [str(mine.id)]

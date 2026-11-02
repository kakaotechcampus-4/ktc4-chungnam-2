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

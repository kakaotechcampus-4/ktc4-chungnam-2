"""maps.api.get_map_for_agent(#522) — agent 스냅샷이 읽는 지도 기간·삭제 여부·지금 구성원. 읽기만 한다."""

from datetime import date, datetime, timedelta, timezone

from auth.models import User
from auth.testing import ensure_users
from maps import api
from maps.models import Map, Membership

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _seed(db, *, deleted=False):
    row = Map(
        title="지도", start_date=date(2026, 10, 20), end_date=date(2026, 10, 22), created_by="user_1",
        deleted_at=T0 if deleted else None,
    )
    db.add(row)
    db.flush()
    db.add(Membership(map_id=row.id, user_id="user_2", role="member", joined_at=T0 + timedelta(minutes=5)))
    db.add(Membership(map_id=row.id, user_id="user_1", role="owner", joined_at=T0))
    db.flush()
    return row.id


def test_returns_period_and_members_in_join_order(db_session):
    map_id = _seed(db_session)

    assert api.get_map_for_agent(db_session, map_id) == {
        "map_id": map_id, "start_date": date(2026, 10, 20), "end_date": date(2026, 10, 22), "deleted": False,
        "members": [
            {"user_id": "user_1", "joined_at": T0},
            {"user_id": "user_2", "joined_at": T0 + timedelta(minutes=5)},
        ],
    }


def test_members_exclude_withdrawn_like_count_members(db_session):
    map_id = _seed(db_session)
    ensure_users(db_session, "user_1", "user_2")
    db_session.get(User, "user_2").deleted_at = T0   # 탈퇴자는 멤버십 행이 남는다(#245)
    db_session.flush()

    result = api.get_map_for_agent(db_session, map_id)

    assert [m["user_id"] for m in result["members"]] == ["user_1"]
    assert len(result["members"]) == api.count_members(db_session, map_id)


def test_deleted_map_is_flagged_with_no_members(db_session):
    map_id = _seed(db_session, deleted=True)

    result = api.get_map_for_agent(db_session, map_id)

    assert result["deleted"] is True
    assert result["members"] == []
    assert result["start_date"] == date(2026, 10, 20)


def test_missing_map_is_none(db_session):
    assert api.get_map_for_agent(db_session, "no_such_map") is None

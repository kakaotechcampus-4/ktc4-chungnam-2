"""api.purge_map_data(#431) — 삭제된 지도의 invites·memberships·maps만 지운다. 살아 있는 지도가 섞이면 거부한다."""

from datetime import datetime, timezone

import pytest

from maps import api
from maps.models import Invite, Map, Membership


def _seed(db, *, deleted):
    row = Map(
        title="지도", start_date=datetime(2026, 10, 1).date(), end_date=datetime(2026, 10, 2).date(),
        created_by="user_1", deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(row)
    db.flush()
    db.add(Membership(map_id=row.id, user_id="user_1", role="owner"))
    db.add(Membership(map_id=row.id, user_id="user_2", role="member"))
    db.add(Invite(token=f"tok_{row.id}", map_id=row.id, created_by="user_1",
                  expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    db.flush()
    return row.id


def test_purge_deletes_only_target_maps_rows(db_session):
    gone, keep = _seed(db_session, deleted=True), _seed(db_session, deleted=True)

    result = api.purge_map_data(db_session, map_ids=[gone])

    assert result == {"invites": 1, "memberships": 2, "maps": 1}
    assert [m.id for m in db_session.query(Map).all()] == [keep]
    assert {m.map_id for m in db_session.query(Membership).all()} == {keep}
    assert {i.map_id for i in db_session.query(Invite).all()} == {keep}


def test_purge_refuses_maps_that_are_not_deleted_and_deletes_nothing(db_session):
    gone, live = _seed(db_session, deleted=True), _seed(db_session, deleted=False)

    with pytest.raises(ValueError, match=live):
        api.purge_map_data(db_session, map_ids=[gone, live])

    assert db_session.query(Map).count() == 2
    assert db_session.query(Membership).count() == 4


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    _seed(db_session, deleted=True)

    assert api.purge_map_data(db_session, map_ids=[]) == {"invites": 0, "memberships": 0, "maps": 0}
    assert db_session.query(Map).count() == 1

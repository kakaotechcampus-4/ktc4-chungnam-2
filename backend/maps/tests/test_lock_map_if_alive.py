"""maps.api.lock_map_if_alive(#512) — agent 저장 트랜잭션 맨 앞에서 지도 행을 FOR UPDATE로 잠그고 살아 있는지 본다.
테스트 트랜잭션은 커밋되지 않아 두 번째 연결로 잠금을 관찰할 수 없으므로, 보낸 SQL을 잡아 FOR UPDATE를 확인한다
(test_lock_member_maps.py와 같은 방식)."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event

from maps import api as maps_api
from maps.models import Map as MapRow


def _map(db, *, deleted=False):
    row = MapRow(title="지도", start_date=date(2026, 10, 20), end_date=date(2026, 10, 22), created_by="user_1",
                 deleted_at=datetime.now(timezone.utc) if deleted else None)
    db.add(row)
    db.flush()
    return row.id


def test_alive_map_is_true(db_session):
    assert maps_api.lock_map_if_alive(db_session, _map(db_session)) is True


def test_deleted_map_is_false(db_session):
    assert maps_api.lock_map_if_alive(db_session, _map(db_session, deleted=True)) is False


def test_missing_map_is_false(db_session):
    assert maps_api.lock_map_if_alive(db_session, "no_such_map") is False


@pytest.mark.parametrize("deleted", [False, True])
def test_locks_the_map_row_with_for_update(db_session, deleted):
    """삭제된 지도도 잠근 뒤에 판정한다 — 삭제와 같은 행에서 줄을 선 결과를 본다."""
    map_id = _map(db_session, deleted=deleted)
    statements = []

    def capture(conn, cursor, statement, *args):
        if statement.startswith("SELECT"):  # 세션이 여는 SAVEPOINT는 거른다
            statements.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        maps_api.lock_map_if_alive(db_session, map_id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    sql = " ".join(statements[0].split())
    assert "FROM maps WHERE maps.id =" in sql
    assert sql.endswith("FOR UPDATE")

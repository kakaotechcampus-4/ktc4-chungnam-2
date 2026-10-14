"""maps.api.lock_member_maps(#435) — 탈퇴가 이 사용자가 속한 지도 행을 id 순서로 FOR UPDATE 잠근다.
테스트 트랜잭션은 커밋되지 않아 두 번째 연결에서 잠금을 관찰할 수 없으므로, 보낸 SQL을 잡아
FOR UPDATE와 정렬을 확인한다."""

from datetime import datetime, timezone

from sqlalchemy import event, update

from auth.testing import session_cookie
from maps import api as maps_api
from maps.models import Map as MapRow


def _create_map(app_client, user_id):
    resp = app_client.post(
        "/maps",
        json={"title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12"},
        cookies=session_cookie(user_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _join(app_client, map_id, user_id, *, owner):
    token = app_client.post(f"/maps/{map_id}/invite", cookies=session_cookie(owner)).json()["token"]
    assert app_client.post(f"/invites/{token}/accept", cookies=session_cookie(user_id)).status_code == 200


def test_locks_every_map_the_user_belongs_to_in_id_order(app_client, db_session):
    owned = _create_map(app_client, "user_1")
    joined = _create_map(app_client, "user_2")
    _join(app_client, joined, "user_1", owner="user_2")  # user_1은 방장인 지도와 일반 구성원인 지도에 모두 속한다
    _create_map(app_client, "user_2")    # user_1과 무관한 지도

    assert maps_api.lock_member_maps(db_session, "user_1") == sorted([owned, joined])


def test_skips_deleted_maps_and_other_users_maps(app_client, db_session):
    kept = _create_map(app_client, "user_1")
    deleted = _create_map(app_client, "user_1")
    db_session.execute(update(MapRow).where(MapRow.id == deleted).values(deleted_at=datetime.now(timezone.utc)))
    db_session.commit()
    _create_map(app_client, "user_2")

    assert maps_api.lock_member_maps(db_session, "user_1") == [kept]
    assert maps_api.lock_member_maps(db_session, "outsider") == []


def test_query_is_for_update_ordered_by_map_id(app_client, db_session):
    _create_map(app_client, "user_1")
    statements = []

    def capture(conn, cursor, statement, *args):
        if statement.startswith("SELECT"):  # 세션이 여는 SAVEPOINT는 거른다
            statements.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        maps_api.lock_member_maps(db_session, "user_1")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    sql = " ".join(statements[0].split())
    assert "ORDER BY maps.id" in sql
    assert sql.endswith("FOR UPDATE")

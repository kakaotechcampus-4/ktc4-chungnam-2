"""탈퇴가 지운 지도의 복구(#1000) — maps.api.restore_maps_deleted_by_withdrawal (conftest.py 참고 — 실제 PostgreSQL 필요).
탈퇴 단계(transfer_or_delete_owned_maps)가 표식을 남기고, 계정 복구가 부르는 이 함수가 표식 지도만 되살린다."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from common.events import EventLog
from maps import api as maps_api
from maps import core
from maps.core import MAP_LIMIT
from maps.models import Map as MapRow
from maps.tests.test_delete_leave_api import _auth, _create_map, _events, _fill_to_limit, _join, _roles

NOW = datetime.now(timezone.utc)   # 모듈이 불러와질 때의 시각 — 경계 테스트는 이 값과 _restore의 now를 같게 쓴다(실행 시각에 기대면 흔들린다)


def _withdraw_owner(db_session, user_id="user_1"):
    maps_api.transfer_or_delete_owned_maps(db_session, user_id)
    db_session.commit()


def _restore(db_session, user_id="user_1", now=None):
    restored = maps_api.restore_maps_deleted_by_withdrawal(db_session, user_id=user_id, now=now or NOW)
    db_session.commit()
    return restored


def _row(db_session, map_id):
    db_session.expire_all()
    return db_session.get(MapRow, map_id)


def test_withdrawal_marks_the_map_it_deletes_with_the_withdrawn_user(app_client, db_session):
    alone = _create_map(app_client, title="혼자")
    _withdraw_owner(db_session)
    assert _row(db_session, alone).deleted_by_withdrawal_of == "user_1"


def test_a_map_deleted_by_withdrawal_comes_back_with_its_marker_cleared(app_client, db_session):
    alone = _create_map(app_client, title="혼자")
    _withdraw_owner(db_session)

    assert _restore(db_session) == [alone]

    row = _row(db_session, alone)
    assert (row.deleted_at, row.deleted_by_withdrawal_of) == (None, None)
    assert _roles(db_session, alone) == {"user_1": "owner"}   # 방장 자리 그대로
    assert len(_events(db_session, alone, "map.restored")) == 1
    assert app_client.get(f"/maps/{alone}", cookies=_auth("user_1")).status_code == 200


def test_a_second_call_restores_nothing(app_client, db_session):
    alone = _create_map(app_client)
    _withdraw_owner(db_session)
    assert _restore(db_session) == [alone]
    assert _restore(db_session) == []
    assert len(_events(db_session, alone, "map.restored")) == 1


def test_a_map_the_owner_deleted_directly_stays_deleted(app_client, db_session):
    direct = _create_map(app_client, title="직접 지움")
    assert app_client.delete(f"/maps/{direct}", cookies=_auth("user_1")).status_code == 204
    assert _row(db_session, direct).deleted_by_withdrawal_of is None

    assert _restore(db_session) == []
    assert _row(db_session, direct).deleted_at is not None


def test_a_map_older_than_thirty_days_stays_deleted(app_client, db_session):
    old = _create_map(app_client, title="오래전")
    fresh = _create_map(app_client, title="최근")
    _withdraw_owner(db_session)
    db_session.execute(update(MapRow).where(MapRow.id == old).values(deleted_at=NOW - core.TRASH_RETENTION))   # 정리 대상과 같은 경계
    db_session.execute(update(MapRow).where(MapRow.id == fresh).values(deleted_at=NOW - core.TRASH_RETENTION + timedelta(minutes=1)))
    db_session.commit()

    assert _restore(db_session) == [fresh]
    assert _row(db_session, old).deleted_at is not None
    assert _row(db_session, old).deleted_by_withdrawal_of == "user_1"   # 표식은 정리 작업이 행째 지운다


def test_a_handed_over_map_is_left_alone(app_client, db_session):
    shared = _create_map(app_client, title="함께")
    _join(app_client, shared, "user_2")
    _withdraw_owner(db_session)

    assert _restore(db_session) == []
    row = _row(db_session, shared)
    assert (row.deleted_at, row.deleted_by_withdrawal_of) == (None, None)
    assert _roles(db_session, shared) == {"user_1": "member", "user_2": "owner"}   # 위임은 되돌리지 않는다(2026-10-30 결정)
    assert _events(db_session, shared, "map.restored") == []


def test_only_the_named_users_maps_come_back(app_client, db_session):
    mine = _create_map(app_client, "user_1", title="내 것")
    theirs = _create_map(app_client, "user_2", title="남의 것")
    _withdraw_owner(db_session, "user_1")
    _withdraw_owner(db_session, "user_2")

    assert _restore(db_session, "user_1") == [mine]
    assert _row(db_session, theirs).deleted_at is not None


def test_the_map_limit_is_not_applied(app_client, db_session):
    """탈퇴 전에 가졌던 지도다 — 그사이 상한까지 채웠어도 되살린다."""
    alone = _create_map(app_client, "user_1", title="혼자")
    _withdraw_owner(db_session)
    _fill_to_limit(app_client, "user_1")

    assert _restore(db_session) == [alone]
    count = db_session.execute(
        select(func.count()).select_from(MapRow).where(MapRow.created_by == "user_1", MapRow.deleted_at.is_(None))
    ).scalar_one()
    assert count == MAP_LIMIT + 1


def test_restoring_through_the_trash_clears_a_withdrawal_marker(app_client, db_session):
    """#464 복구로 먼저 살린 지도는 표식이 비어야 한다 — 남아 있으면 나중에 직접 지운 뒤 계정 복구가 되살린다."""
    alone = _create_map(app_client)
    _withdraw_owner(db_session)
    assert app_client.post(f"/maps/{alone}/restore", cookies=_auth("user_1")).status_code == 200
    assert _row(db_session, alone).deleted_by_withdrawal_of is None

    assert app_client.delete(f"/maps/{alone}", cookies=_auth("user_1")).status_code == 204
    assert _restore(db_session) == []
    assert _row(db_session, alone).deleted_at is not None


def test_deleting_directly_overwrites_a_stale_marker(app_client, db_session):
    alone = _create_map(app_client)
    db_session.execute(update(MapRow).where(MapRow.id == alone).values(deleted_by_withdrawal_of="user_1"))
    db_session.commit()
    assert app_client.delete(f"/maps/{alone}", cookies=_auth("user_1")).status_code == 204
    assert _row(db_session, alone).deleted_by_withdrawal_of is None


def test_purge_removes_a_marked_map_with_its_marker(app_client, db_session):
    alone = _create_map(app_client)
    _withdraw_owner(db_session)
    db_session.execute(update(MapRow).where(MapRow.id == alone).values(deleted_at=NOW - core.TRASH_RETENTION - timedelta(days=1)))
    db_session.commit()

    maps_api.purge_map_data(db_session, map_ids=[alone])   # maps.purge가 지도마다 부르는 maps 몫(다른 모듈 테이블은 이 테스트에 없다)
    db_session.commit()

    assert db_session.get(MapRow, alone) is None
    assert _restore(db_session) == []
    assert db_session.execute(select(func.count()).select_from(EventLog).where(EventLog.map_id == alone, EventLog.type == "map.restored")).scalar_one() == 0


# --- 복구와 정리의 경쟁(Codex 검수) ---

def test_purge_skips_a_map_restored_while_it_waited_for_the_row_lock(test_engine):
    """복구가 지도 행을 쥔 채 정리가 기다리다가, 복구가 커밋된 뒤 그 지도를 건너뛴다 — 방금 복구한 지도를 정리가 지우면 안 된다.
    커밋되는 별도 연결 두 개로 만든다(db_session은 커밋하지 않아 잠금을 관찰할 수 없다)."""
    import threading

    from sqlalchemy.orm import sessionmaker

    from maps import purge
    from maps.models import Membership as MembershipRow

    factory = sessionmaker(bind=test_engine)
    now = datetime.now(timezone.utc)
    with factory() as session:
        row = MapRow(title="경쟁", start_date=now.date(), end_date=now.date(), created_by="race_user",
                     deleted_at=now - core.TRASH_RETENTION - timedelta(days=1))
        session.add(row)
        session.flush()
        session.add(MembershipRow(map_id=row.id, user_id="race_user", role="owner"))
        session.commit()
        map_id = row.id

    holder = factory()
    try:
        holder.execute(select(MapRow.id).where(MapRow.id == map_id).with_for_update())   # 복구가 행을 쥔 상태
        outcome = {}

        def run_purge():
            session = factory()
            try:
                outcome["result"] = purge.purge(session, now=now, older_than_days=core.TRASH_RETENTION.days)
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                outcome["result"] = exc
            finally:
                session.close()

        thread = threading.Thread(target=run_purge)
        thread.start()
        thread.join(timeout=1)
        assert thread.is_alive()   # 정리는 잠금에서 기다린다 — 자식 데이터를 아직 지우지 못했다
        holder.execute(update(MapRow).where(MapRow.id == map_id).values(deleted_at=None, deleted_by_withdrawal_of=None))
        holder.commit()   # 복구 커밋
        thread.join(timeout=15)

        assert not isinstance(outcome["result"], Exception), outcome
        assert outcome["result"][0] == 0   # 복구된 지도는 정리 대상이 아니다
        with factory() as session:
            assert session.get(MapRow, map_id) is not None
            assert session.execute(select(func.count()).select_from(MembershipRow).where(MembershipRow.map_id == map_id)).scalar_one() == 1
    finally:
        holder.close()
        with factory() as session:
            session.execute(MembershipRow.__table__.delete().where(MembershipRow.map_id == map_id))
            session.execute(MapRow.__table__.delete().where(MapRow.id == map_id))
            session.commit()

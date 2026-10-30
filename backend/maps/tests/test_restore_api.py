"""삭제한 지도 복구(#464) — GET /maps/trash, POST /maps/{mapId}/restore (conftest.py 참고 — 실제 PostgreSQL 필요).

30일 판정은 서버 시각 기준이라, 테스트는 deleted_at을 직접 옮겨 경계를 만든다. 동시 요청은 커밋되는 별도 연결
두 개로 실제 잠금을 본다(db_session은 커밋하지 않아 잠금을 관찰할 수 없다)."""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import sessionmaker

from auth.models import User, UserIdentity
from auth.testing import ensure_users, session_cookie
from common.events import EventLog
from maps import core, service
from maps.core import MAP_LIMIT
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from maps.schemas import MapCreateRequest

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _auth(user_id):
    return session_cookie(user_id)


def _create_map(app_client, user_id="user_1", title="부산 여행"):
    resp = app_client.post(
        "/maps", json={"title": title, "start_date": "2026-10-10", "end_date": "2026-10-12"}, cookies=_auth(user_id)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _join(app_client, map_id, *user_ids):
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()["token"]
    for user_id in user_ids:
        assert app_client.post(f"/invites/{token}/accept", cookies=_auth(user_id)).status_code == 200


def _delete(app_client, map_id, user_id="user_1"):
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth(user_id)).status_code == 204


def _deleted_ago(db_session, map_id, age):
    db_session.execute(update(MapRow).where(MapRow.id == map_id).values(deleted_at=datetime.now(timezone.utc) - age))
    db_session.flush()


def _restore(app_client, map_id, user_id="user_1"):
    return app_client.post(f"/maps/{map_id}/restore", cookies=_auth(user_id))


def _parse(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _trash(app_client, user_id="user_1"):
    resp = app_client.get("/maps/trash", cookies=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- core ----------

def test_purge_due_matches_the_purge_cutoff():
    deleted_at = NOW - core.TRASH_RETENTION
    assert core.is_purge_due(deleted_at, NOW) is True   # maps.purge는 deleted_at <= now - 30일을 지운다
    assert core.is_purge_due(deleted_at + timedelta(seconds=1), NOW) is False


def test_days_left_rounds_up_and_never_goes_negative():
    assert core.days_left(NOW, NOW) == 30
    assert core.days_left(NOW - timedelta(days=29, hours=1), NOW) == 1
    assert core.days_left(NOW - timedelta(days=31), NOW) == 0


# ---------- POST /maps/{mapId}/restore ----------

def test_owner_restores_and_everything_comes_back(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _delete(app_client, map_id)
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 404

    resp = _restore(app_client, map_id)

    assert resp.status_code == 200
    assert resp.json()["id"] == map_id
    assert resp.json()["member_count"] == 2
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 200
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).status_code == 200  # 구성원도 다시 본다
    ids = [m["id"] for m in app_client.get("/maps", cookies=_auth("user_1")).json()["items"]]
    assert map_id in ids
    assert db_session.execute(select(MapRow.deleted_at).where(MapRow.id == map_id)).scalar_one() is None
    assert db_session.execute(
        select(func.count()).select_from(EventLog).where(EventLog.type == "map.restored", EventLog.map_id == map_id)
    ).scalar_one() == 1


def test_restore_event_is_public_with_map_id(app_client, db_session):
    map_id = _create_map(app_client)
    _delete(app_client, map_id)
    _restore(app_client, map_id)
    event = db_session.execute(select(EventLog).where(EventLog.type == "map.restored")).scalar_one()
    assert event.channel == "public"
    assert event.payload == {"map_id": map_id}
    assert event.recipient_user_id is None


def test_restoring_an_already_restored_map_is_200_and_records_one_event(app_client, db_session):
    map_id = _create_map(app_client)
    _delete(app_client, map_id)
    assert _restore(app_client, map_id).status_code == 200
    again = _restore(app_client, map_id)
    assert again.status_code == 200
    assert again.json()["id"] == map_id
    assert db_session.execute(
        select(func.count()).select_from(EventLog).where(EventLog.type == "map.restored")
    ).scalar_one() == 1


def test_restoring_a_never_deleted_map_is_200_for_the_owner_and_403_for_a_member(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert _restore(app_client, map_id).status_code == 200
    assert _restore(app_client, map_id, "user_2").status_code == 403


def test_a_member_who_is_not_the_owner_gets_403_and_the_map_stays_deleted(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _delete(app_client, map_id)

    resp = _restore(app_client, map_id, "user_2")

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
    assert db_session.execute(select(MapRow.deleted_at).where(MapRow.id == map_id)).scalar_one() is not None


def test_a_non_member_and_an_unknown_map_are_404(app_client):
    map_id = _create_map(app_client)
    _delete(app_client, map_id)
    assert _restore(app_client, map_id, "outsider").status_code == 404
    assert _restore(app_client, "no_such_map").status_code == 404


def test_the_new_owner_restores_after_the_owner_handed_over(app_client, db_session):
    """방장 판정은 memberships.role이다 — 삭제 뒤에 위임이 일어났어도 지금의 방장이 복구한다."""
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _delete(app_client, map_id)
    db_session.execute(update(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_1").values(role="member"))
    db_session.execute(update(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == "user_2").values(role="owner"))
    db_session.flush()

    assert _restore(app_client, map_id, "user_2").status_code == 200


def test_thirty_days_boundary_is_judged_at_request_time_not_at_purge_time(app_client, db_session):
    just_inside = _create_map(app_client, title="아직")
    just_outside = _create_map(app_client, title="지남")
    _delete(app_client, just_inside)
    _delete(app_client, just_outside)
    _deleted_ago(db_session, just_inside, core.TRASH_RETENTION - timedelta(minutes=1))
    _deleted_ago(db_session, just_outside, core.TRASH_RETENTION + timedelta(minutes=1))

    assert _restore(app_client, just_inside).status_code == 200

    resp = _restore(app_client, just_outside)   # maps.purge는 안 돌았다 — 행이 그대로 있어도 410
    assert resp.status_code == 410
    assert resp.json()["code"] == "MAP_PURGED"
    assert db_session.execute(select(MapRow.deleted_at).where(MapRow.id == just_outside)).scalar_one() is not None


def test_a_purged_map_with_no_row_is_404(app_client, db_session):
    map_id = _create_map(app_client)
    _delete(app_client, map_id)
    db_session.execute(delete(MembershipRow).where(MembershipRow.map_id == map_id))
    db_session.execute(delete(MapRow).where(MapRow.id == map_id))
    db_session.flush()
    assert _restore(app_client, map_id).status_code == 404


def test_restore_at_the_map_limit_is_409_and_one_below_succeeds(app_client, db_session):
    target = _create_map(app_client, title="복구할 지도")
    _delete(app_client, target)
    for n in range(MAP_LIMIT - 1):   # 19개 — 복구하면 20개로 상한까지 허용
        _create_map(app_client, title=f"지도 {n}")
    assert _restore(app_client, target).status_code == 200

    _delete(app_client, target)
    _create_map(app_client, title="스무 번째")   # 이미 20개
    resp = _restore(app_client, target)

    assert resp.status_code == 409
    assert resp.json()["code"] == "MAP_LIMIT"
    assert resp.json()["detail"] == {"limit": MAP_LIMIT, "count": MAP_LIMIT}
    assert db_session.execute(select(MapRow.deleted_at).where(MapRow.id == target)).scalar_one() is not None
    assert db_session.execute(
        select(func.count()).select_from(EventLog).where(EventLog.type == "map.restored")
    ).scalar_one() == 1   # 첫 복구 하나뿐 — 막힌 복구는 이벤트도 남기지 않는다


def test_a_purge_due_map_is_410_even_when_the_user_is_at_the_limit(app_client, db_session):
    target = _create_map(app_client, title="오래된 지도")
    _delete(app_client, target)
    _deleted_ago(db_session, target, core.TRASH_RETENTION + timedelta(days=1))
    for n in range(MAP_LIMIT):
        _create_map(app_client, title=f"지도 {n}")
    assert _restore(app_client, target).json()["code"] == "MAP_PURGED"


def test_restoring_leaves_members_pins_and_invites_as_they_were(app_client, db_session):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth("user_1")).json()["token"]
    _delete(app_client, map_id)
    assert app_client.get(f"/invites/{token}").status_code == 404   # 삭제 중에는 초대도 404

    _restore(app_client, map_id)

    assert app_client.get(f"/invites/{token}").status_code == 200
    members = app_client.get(f"/maps/{map_id}/members", cookies=_auth("user_2")).json()
    assert sorted(m["user_id"] for m in members) == ["user_1", "user_2"]


# ---------- GET /maps/trash ----------

def test_trash_lists_my_deleted_maps_newest_first_with_purge_info(app_client, db_session):
    older = _create_map(app_client, title="먼저 지운 지도")
    newer = _create_map(app_client, title="나중에 지운 지도")
    _join(app_client, newer, "user_2")
    _delete(app_client, older)
    _delete(app_client, newer)
    _deleted_ago(db_session, older, timedelta(days=10, hours=1))
    _deleted_ago(db_session, newer, timedelta(hours=1))

    body = _trash(app_client)

    assert body["retention_days"] == 30
    assert [m["id"] for m in body["items"]] == [newer, older]
    first, second = body["items"]
    assert first["title"] == "나중에 지운 지도"
    assert first["member_count"] == 2
    assert first["pin_count"] == 0
    assert first["days_left"] == 30
    assert second["days_left"] == 20
    deleted_at = _parse(first["deleted_at"])
    assert _parse(first["purge_at"]) == deleted_at + timedelta(days=30)


def test_trash_only_has_maps_where_i_am_the_owner(app_client):
    mine = _create_map(app_client, "user_1", title="내가 방장")
    theirs = _create_map(app_client, "user_2", title="남이 방장")
    _join_user_1 = app_client.post(f"/maps/{theirs}/invite", cookies=_auth("user_2")).json()["token"]
    assert app_client.post(f"/invites/{_join_user_1}/accept", cookies=_auth("user_1")).status_code == 200
    _delete(app_client, mine)
    _delete(app_client, theirs, "user_2")

    assert [m["id"] for m in _trash(app_client, "user_1")["items"]] == [mine]
    assert [m["id"] for m in _trash(app_client, "user_2")["items"]] == [theirs]
    assert _trash(app_client, "outsider")["items"] == []


def test_trash_leaves_out_alive_maps_and_expired_ones(app_client, db_session):
    alive = _create_map(app_client, title="살아 있음")
    inside = _create_map(app_client, title="기한 안")
    outside = _create_map(app_client, title="기한 지남")
    _delete(app_client, inside)
    _delete(app_client, outside)
    _deleted_ago(db_session, inside, core.TRASH_RETENTION - timedelta(minutes=1))
    _deleted_ago(db_session, outside, core.TRASH_RETENTION)   # 정리 대상과 같은 경계

    ids = [m["id"] for m in _trash(app_client)["items"]]

    assert ids == [inside]
    assert alive not in ids


def test_a_restored_map_leaves_the_trash(app_client):
    map_id = _create_map(app_client)
    _delete(app_client, map_id)
    assert [m["id"] for m in _trash(app_client)["items"]] == [map_id]
    _restore(app_client, map_id)
    assert _trash(app_client)["items"] == []


def test_trash_requires_login(app_client):
    assert app_client.get("/maps/trash").status_code == 401


def test_trash_is_not_read_as_a_map_id(app_client):
    """/maps/trash가 /maps/{mapId}로 가면 404(비구성원)가 된다 — 라우트 순서."""
    assert app_client.get("/maps/trash", cookies=_auth("user_1")).status_code == 200


def test_trash_carries_the_region(app_client, db_session):
    resp = app_client.post(
        "/maps",
        json={"title": "지역 있음", "start_date": "2026-10-10", "end_date": "2026-10-12",
              "region": {"label": "서울", "lat": 37.5665, "lng": 126.978}},
        cookies=_auth("user_1"),
    )
    map_id = resp.json()["id"]
    _delete(app_client, map_id)
    item = _trash(app_client)["items"][0]
    assert item["region"]["label"] == "서울"


# ---------- 동시 요청 (커밋되는 별도 연결) ----------

def _run_concurrently(test_engine, jobs):
    """각 job(session)을 자기 연결에서 동시에 시작해 커밋한다. 결과 또는 예외를 순서대로 돌려준다."""
    factory = sessionmaker(bind=test_engine)
    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)

    def worker(i, job):
        session = factory()
        try:
            barrier.wait(timeout=10)
            results[i] = job(session)
            session.commit()
        except Exception as exc:  # noqa: BLE001 — 결과로 돌려줘 단언한다
            session.rollback()
            results[i] = exc
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _committed_owner_with_deleted_maps(test_engine, count, *, alive=0):
    """커밋된 사용자 하나와 그 사람이 방장인 삭제된 지도 count개, 살아 있는 지도 alive개."""
    factory = sessionmaker(bind=test_engine)
    user_id = f"concurrent_{uuid.uuid4().hex[:8]}"
    with factory() as session:
        ensure_users(session, user_id)
        deleted, living = [], []
        for n in range(count + alive):
            row = MapRow(title=f"지도 {n}", start_date=NOW.date(), end_date=NOW.date(), created_by=user_id,
                         deleted_at=datetime.now(timezone.utc) - timedelta(days=1) if n < count else None)
            session.add(row)
            session.flush()
            session.add(MembershipRow(map_id=row.id, user_id=user_id, role="owner"))
            (deleted if n < count else living).append(row.id)
        session.commit()
    return user_id, deleted, living


def _cleanup(test_engine, user_id):
    factory = sessionmaker(bind=test_engine)
    with factory() as session:
        map_ids = session.execute(select(MembershipRow.map_id).where(MembershipRow.user_id == user_id)).scalars().all()
        session.execute(delete(EventLog).where(EventLog.map_id.in_(map_ids)))
        session.execute(delete(MembershipRow).where(MembershipRow.map_id.in_(map_ids)))
        session.execute(delete(MapRow).where(MapRow.id.in_(map_ids)))
        session.execute(delete(UserIdentity).where(UserIdentity.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_two_concurrent_restores_of_the_same_map_restore_once(test_engine):
    user_id, (map_id,), _ = _committed_owner_with_deleted_maps(test_engine, 1)
    try:
        results = _run_concurrently(test_engine, [lambda s: service.restore_map(s, map_id=map_id, user_id=user_id)] * 2)

        assert all(not isinstance(r, Exception) for r in results), results   # 둘 다 200 — 뒤의 요청은 이미 복구된 지도
        assert [r.id for r in results] == [map_id, map_id]
        with sessionmaker(bind=test_engine)() as session:
            assert session.execute(
                select(func.count()).select_from(EventLog).where(EventLog.type == "map.restored", EventLog.map_id == map_id)
            ).scalar_one() == 1
            assert session.execute(select(MapRow.deleted_at).where(MapRow.id == map_id)).scalar_one() is None
    finally:
        _cleanup(test_engine, user_id)


def test_concurrent_restores_of_two_maps_cannot_cross_the_limit(test_engine):
    """19개를 가진 사람이 삭제한 지도 둘을 동시에 복구하면 하나만 20개째가 된다."""
    user_id, deleted, _ = _committed_owner_with_deleted_maps(test_engine, 2, alive=MAP_LIMIT - 1)
    try:
        results = _run_concurrently(
            test_engine, [lambda s, m=m: service.restore_map(s, map_id=m, user_id=user_id) for m in deleted]
        )

        failures = [r for r in results if isinstance(r, Exception)]
        assert len(failures) == 1, results
        assert failures[0].code == "MAP_LIMIT"
        with sessionmaker(bind=test_engine)() as session:
            assert service._my_map_count(session, user_id) == MAP_LIMIT
    finally:
        _cleanup(test_engine, user_id)


def test_a_concurrent_create_and_restore_cannot_cross_the_limit(test_engine):
    user_id, (deleted_id,), _ = _committed_owner_with_deleted_maps(test_engine, 1, alive=MAP_LIMIT - 1)
    create = MapCreateRequest(title="새 지도", start_date=NOW.date(), end_date=NOW.date())
    try:
        results = _run_concurrently(test_engine, [
            lambda s: service.restore_map(s, map_id=deleted_id, user_id=user_id),
            lambda s: service.create_map(s, req=create, creator_id=user_id),
        ])

        assert sum(isinstance(r, Exception) for r in results) == 1, results
        with sessionmaker(bind=test_engine)() as session:
            assert service._my_map_count(session, user_id) == MAP_LIMIT
    finally:
        _cleanup(test_engine, user_id)

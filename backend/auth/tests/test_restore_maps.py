"""탈퇴 계정 복구 때 탈퇴가 지운 내 지도도 돌아온다(#1000) — restore_account가 maps.api.restore_maps_deleted_by_withdrawal을 부른다.
실제 PostgreSQL. 탈퇴는 service.withdraw_user 그대로(방장 지도는 후임에게 넘기고, 넘길 사람이 없으면 지운다)."""

from sqlalchemy import select

from auth import service
from auth.testing import create_kakao_user, session_cookie
from auth.tests.test_pending import _choose, _login_to_pending
from auth.tests.test_router import kakao_configured  # noqa: F401 — 픽스처
from common.events import EventLog
from maps.models import Map as MapRow
from maps.models import Membership


def _setup(db_session):
    create_kakao_user(db_session, "old", provider_user_id="77", display_name="영희")
    create_kakao_user(db_session, "friend", provider_user_id="88", display_name="철수")


def _create_map(app_client, title):
    resp = app_client.post(
        "/maps", json={"title": title, "start_date": "2026-10-10", "end_date": "2026-10-12"}, cookies=session_cookie("old"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _share_with_friend(app_client, map_id):
    token = app_client.post(f"/maps/{map_id}/invite", cookies=session_cookie("old")).json()["token"]
    assert app_client.post(f"/invites/{token}/accept", cookies=session_cookie("friend")).status_code == 200


def _withdraw(db_session):
    service.withdraw_user(db_session, user_id="old")
    db_session.commit()


def _map(db_session, map_id):
    db_session.expire_all()
    return db_session.get(MapRow, map_id)


def _roles(db_session, map_id):
    return dict(db_session.execute(select(Membership.user_id, Membership.role).where(Membership.map_id == map_id)).all())


def _restored_events(db_session, map_id):
    return db_session.execute(select(EventLog).where(EventLog.map_id == map_id, EventLog.type == "map.restored")).scalars().all()


def test_restore_brings_back_a_map_deleted_by_the_withdrawal(app_client, db_session, monkeypatch, kakao_configured):
    _setup(db_session)
    alone = _create_map(app_client, "혼자")
    _withdraw(db_session)
    assert _map(db_session, alone).deleted_at is not None
    _login_to_pending(app_client, monkeypatch)

    assert _choose(app_client, "restore").status_code == 200

    row = _map(db_session, alone)
    assert (row.deleted_at, row.deleted_by_withdrawal_of) == (None, None)
    assert _roles(db_session, alone) == {"old": "owner"}
    assert len(_restored_events(db_session, alone)) == 1
    assert app_client.get(f"/maps/{alone}").status_code == 200   # 복구 응답의 새 세션으로 바로 보인다


def test_restore_returns_a_handed_over_map_as_a_plain_member(app_client, db_session, monkeypatch, kakao_configured):
    _setup(db_session)
    shared = _create_map(app_client, "같이")
    _share_with_friend(app_client, shared)
    _withdraw(db_session)
    _login_to_pending(app_client, monkeypatch)

    assert _choose(app_client, "restore").status_code == 200

    assert _map(db_session, shared).deleted_at is None
    assert _roles(db_session, shared) == {"friend": "owner", "old": "member"}   # 방장은 후임 그대로
    assert _restored_events(db_session, shared) == []   # 지워진 적이 없어 되살림도 없다


def test_restore_leaves_a_map_the_user_deleted_directly(app_client, db_session, monkeypatch, kakao_configured):
    _setup(db_session)
    direct = _create_map(app_client, "직접 지움")
    assert app_client.delete(f"/maps/{direct}", cookies=session_cookie("old")).status_code == 204
    _withdraw(db_session)
    _login_to_pending(app_client, monkeypatch)

    assert _choose(app_client, "restore").status_code == 200

    assert _map(db_session, direct).deleted_at is not None


def test_restart_does_not_bring_the_map_back(app_client, db_session, monkeypatch, kakao_configured):
    _setup(db_session)
    alone = _create_map(app_client, "혼자")
    _withdraw(db_session)
    _login_to_pending(app_client, monkeypatch)

    assert _choose(app_client, "restart").status_code == 201

    assert _map(db_session, alone).deleted_at is not None
    assert _restored_events(db_session, alone) == []


def test_a_second_restore_is_rejected_and_restores_nothing_twice(app_client, db_session, monkeypatch, kakao_configured):
    _setup(db_session)
    alone = _create_map(app_client, "혼자")
    _withdraw(db_session)
    _login_to_pending(app_client, monkeypatch)

    assert _choose(app_client, "restore").status_code == 200
    second = _choose(app_client, "restore")

    assert second.status_code == 404 and second.json()["code"] == "NO_PENDING_LOGIN"
    assert _map(db_session, alone).deleted_at is None
    assert len(_restored_events(db_session, alone)) == 1

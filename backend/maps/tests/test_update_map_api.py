"""
PATCH /maps/{mapId}(#465) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
"""

from sqlalchemy import select

from common.events import EventLog
from maps.core import validate_map_update, MapRecord
from maps.tests.test_delete_leave_api import _auth, _create_map, _join

from datetime import date

import pytest

from common.errors import AppError

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}


def _patch(app_client, map_id, body, user_id="user_1"):
    return app_client.patch(f"/maps/{map_id}", json=body, cookies=_auth(user_id))


def _updated_events(db_session, map_id):
    return db_session.execute(
        select(EventLog).where(EventLog.map_id == map_id, EventLog.type == "map.updated")
    ).scalars().all()


def test_owner_updates_only_the_sent_fields(app_client):
    map_id = _create_map(app_client)
    resp = _patch(app_client, map_id, {"title": "  제주 여행  "})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "제주 여행"
    assert (body["start_date"], body["end_date"]) == ("2026-10-10", "2026-10-12")
    assert body["permissions"]["can_edit"] is True
    assert body["my_role"] == "owner"
    assert "region" not in body


def test_end_date_alone_is_checked_against_the_existing_start_date(app_client):
    map_id = _create_map(app_client)
    assert _patch(app_client, map_id, {"end_date": "2026-10-09"}).status_code == 422
    ok = _patch(app_client, map_id, {"end_date": "2026-10-10"})  # 같은 날(당일치기)
    assert ok.status_code == 200 and ok.json()["end_date"] == "2026-10-10"
    # 시작일만 앞당겨도, 기존 종료일 뒤로 밀면 422
    assert _patch(app_client, map_id, {"start_date": "2026-10-11"}).status_code == 422


def test_region_can_be_set_and_changed_but_not_cleared(app_client):
    map_id = _create_map(app_client)
    set_ = _patch(app_client, map_id, {"region": REGION})
    assert set_.status_code == 200 and set_.json()["region"] == REGION
    moved = _patch(app_client, map_id, {"region": {"label": "서울", "lat": 37.5665, "lng": 126.978}})
    assert moved.json()["region"]["label"] == "서울"
    # 다른 필드만 고치면 지역은 그대로다
    assert _patch(app_client, map_id, {"title": "새 제목"}).json()["region"]["label"] == "서울"
    assert _patch(app_client, map_id, {"region": None}).status_code == 422


@pytest.mark.parametrize("body", [
    {},
    {"title": None},
    {"title": "   "},
    {"title": "가" * 101},
    {"region": {"label": "부산"}},
    {"region": {"label": "부산", "lat": 95, "lng": 129}},
])
def test_invalid_bodies_are_422_and_change_nothing(app_client, body):
    map_id = _create_map(app_client)
    resp = _patch(app_client, map_id, body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["title"] == "부산 여행"


def test_member_gets_403_outsider_404_anonymous_401(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert _patch(app_client, map_id, {"title": "x"}, "user_2").status_code == 403
    assert _patch(app_client, map_id, {"title": "x"}, "outsider").status_code == 404
    assert app_client.patch(f"/maps/{map_id}", json={"title": "x"}).status_code == 401
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["title"] == "부산 여행"


def test_deleted_map_is_404(app_client):
    map_id = _create_map(app_client)
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    assert _patch(app_client, map_id, {"title": "x"}).status_code == 404


def test_map_updated_event_is_recorded_with_the_new_values(app_client, db_session):
    map_id = _create_map(app_client)
    _patch(app_client, map_id, {"title": "제주", "region": REGION})
    (event,) = _updated_events(db_session, map_id)
    assert event.channel == "public"
    assert event.payload == {
        "map_id": map_id, "title": "제주", "start_date": "2026-10-10", "end_date": "2026-10-12", "region": REGION,
    }


def test_no_event_when_the_update_is_rejected(app_client, db_session):
    map_id = _create_map(app_client)
    _patch(app_client, map_id, {"title": " "})
    _patch(app_client, map_id, {"title": "x"}, "outsider")
    assert _updated_events(db_session, map_id) == []


def test_member_sees_can_edit_false_on_the_map(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()["permissions"]["can_edit"] is False
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["permissions"]["can_edit"] is True


def test_validate_map_update_merges_with_current_values():
    current = MapRecord(id="m", title="옛", start_date=date(2026, 10, 10), end_date=date(2026, 10, 12), created_by="u")
    merged = validate_map_update(current, title=None, start_date=None, end_date=date(2026, 10, 20), region=None)
    assert (merged.title, merged.end_date, merged.region) == ("옛", date(2026, 10, 20), None)
    with pytest.raises(AppError):
        validate_map_update(current, title=None, start_date=date(2026, 10, 13), end_date=None, region=None)


@pytest.mark.parametrize("body", [{"title": ""}, {"region": {"label": "부산", "lat": 0, "lng": 180.5}}])
def test_patch_rejects_what_the_spec_forbids_with_validation_error(app_client, body):
    """스펙 제약(title minLength 1, region lat/lng 범위, #733)이 요청 모델에서 막힌다 — 코드는 그대로 422 VALIDATION_ERROR."""
    map_id = _create_map(app_client)
    resp = _patch(app_client, map_id, body)
    assert (resp.status_code, resp.json()["code"]) == (422, "VALIDATION_ERROR")


def test_date_change_notifies_shortlist_in_same_transaction(app_client, db_session, monkeypatch):
    from maps import service

    map_id = _create_map(app_client)
    calls = []

    def unassign(db, *, map_id, start_date, end_date):
        calls.append((db, map_id, start_date, end_date))
        return 0

    monkeypatch.setattr(service.shortlist_api, "unassign_outside_dates", unassign)
    assert _patch(app_client, map_id, {"title": "새 이름"}).status_code == 200
    assert calls == []
    assert _patch(app_client, map_id, {"end_date": "2026-10-11"}).status_code == 200
    assert calls == [(db_session, map_id, date(2026, 10, 10), date(2026, 10, 11))]
    assert _updated_events(db_session, map_id)[-1].payload["end_date"] == "2026-10-11"


def test_invalid_date_change_does_not_notify_shortlist(app_client, monkeypatch):
    from maps import service

    map_id = _create_map(app_client)
    calls = []
    monkeypatch.setattr(service.shortlist_api, "unassign_outside_dates", lambda *args, **kwargs: calls.append(1))
    assert _patch(app_client, map_id, {"end_date": "2026-10-09"}).status_code == 422
    assert calls == []


# ---- 여행 기간 상한(#1371) ----

def _post(app_client, start, end):
    return app_client.post("/maps", json={"title": "긴 여행", "start_date": start, "end_date": end}, cookies=_auth("user_1"))


def test_create_allows_90_days_and_blocks_91(app_client):
    assert _post(app_client, "2026-01-01", "2026-03-31").status_code == 201  # 90일(1/1~3/31)
    resp = _post(app_client, "2026-01-01", "2026-04-01")  # 91일
    assert resp.status_code == 422
    body = resp.json()
    assert (body["code"], body["detail"]) == ("TRIP_TOO_LONG", {"limit": 90})


def test_create_one_day_trip_is_fine(app_client):
    assert _post(app_client, "2026-05-05", "2026-05-05").status_code == 201


def test_patch_blocks_dates_over_the_limit_and_allows_90(app_client):
    map_id = _post(app_client, "2026-01-01", "2026-01-10").json()["id"]
    assert _patch(app_client, map_id, {"end_date": "2026-03-31"}).status_code == 200  # 90일
    resp = _patch(app_client, map_id, {"end_date": "2026-04-01"})  # 종료일만 늘려 91일
    assert resp.status_code == 422
    assert (resp.json()["code"], resp.json()["detail"]) == ("TRIP_TOO_LONG", {"limit": 90})
    assert _patch(app_client, map_id, {"start_date": "2025-12-31"}).status_code == 422  # 시작일만 당겨도 91일


def test_patch_title_only_is_allowed_on_a_map_already_over_the_limit(app_client, db_session):
    from sqlalchemy import update

    from maps.models import Map as MapRow

    map_id = _post(app_client, "2026-01-01", "2026-01-10").json()["id"]
    db_session.execute(update(MapRow).where(MapRow.id == map_id).values(end_date=date(2026, 6, 30)))  # 181일
    db_session.commit()
    resp = _patch(app_client, map_id, {"title": "제목만 수정"})
    assert resp.status_code == 200 and resp.json()["title"] == "제목만 수정"


def test_list_maps_reports_trip_max_days(app_client):
    resp = app_client.get("/maps", cookies=_auth("user_1"))
    assert resp.json()["trip_max_days"] == 90

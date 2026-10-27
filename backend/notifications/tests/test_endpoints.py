"""엔드포인트 4개(GET·POST /me/notifications, GET·PUT /me/notification-prefs) — 로그인만 필요하다."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from notifications import api
from notifications.models import Notification


def _make(db, user_id, n=1, *, type="pin_reaction", start=None, message="m"):
    """created_at을 일정 간격으로 벌려 만든다 — 먼저 만든 것이 더 오래된 알림이다. 만든 id를 오래된 순으로."""
    start = start or datetime(2026, 10, 1, tzinfo=timezone.utc)
    ids = []
    for i in range(n):
        nid = api.notify(db, user_id=user_id, type=type, map_id="m1", map_title="부산", message=f"{message}{i}", pin_id="p1")
        db.get(Notification, nid).created_at = start + timedelta(minutes=i)
        ids.append(str(nid))
    db.flush()
    return ids


@pytest.mark.parametrize("method,url,body", [
    ("get", "/me/notifications", None),
    ("post", "/me/notifications/read", {}),
    ("get", "/me/notification-prefs", None),
    ("put", "/me/notification-prefs", {"prefs": [{"type": "pin_reaction", "enabled": False}]}),
])
def test_requires_login(app_client, method, url, body):
    r = getattr(app_client, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"


def test_list_is_newest_first_with_spec_fields(app_client, db_session, as_a):
    _make(db_session, "user_a", 3)
    r = app_client.get("/me/notifications", cookies=as_a)
    assert r.status_code == 200
    body = r.json()
    assert [i["message"] for i in body["items"]] == ["m2", "m1", "m0"]
    assert body["unread_count"] == 3 and "next_before" not in body
    item = body["items"][0]
    assert set(item) == {"id", "type", "map_id", "map_title", "pin_id", "message", "created_at", "read"}
    assert item["read"] is False and item["map_title"] == "부산" and item["pin_id"] == "p1"


def test_list_omits_pin_id_and_title_when_absent(app_client, db_session, as_a):
    api.notify(db_session, user_id="user_a", type="owner_changed", map_id="m1", map_title=None, message="방장")
    item = app_client.get("/me/notifications", cookies=as_a).json()["items"][0]
    assert "pin_id" not in item and "map_title" not in item


def test_list_only_shows_my_notifications(app_client, db_session, as_a):
    _make(db_session, "user_a", 1, message="mine")
    _make(db_session, "user_b", 2, message="theirs")
    body = app_client.get("/me/notifications", cookies=as_a).json()
    assert [i["message"] for i in body["items"]] == ["mine0"] and body["unread_count"] == 1


def test_paging_with_before_covers_everything_once(app_client, db_session, as_a):
    _make(db_session, "user_a", 5)
    first = app_client.get("/me/notifications", params={"limit": 2}, cookies=as_a).json()
    assert [i["message"] for i in first["items"]] == ["m4", "m3"] and first["unread_count"] == 5
    second = app_client.get("/me/notifications", params={"limit": 2, "before": first["next_before"]}, cookies=as_a).json()
    assert [i["message"] for i in second["items"]] == ["m2", "m1"]
    third = app_client.get("/me/notifications", params={"limit": 2, "before": second["next_before"]}, cookies=as_a).json()
    assert [i["message"] for i in third["items"]] == ["m0"] and "next_before" not in third


def test_paging_does_not_skip_rows_with_the_same_timestamp(app_client, db_session, as_a):
    same = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(4):
        nid = api.notify(db_session, user_id="user_a", type="pin_reaction", map_id="m1", map_title=None, message=f"s{i}")
        db_session.get(Notification, nid).created_at = same
    db_session.flush()
    seen, before = [], None
    for _ in range(4):
        params = {"limit": 1, **({"before": before} if before else {})}
        page = app_client.get("/me/notifications", params=params, cookies=as_a).json()
        seen += [i["id"] for i in page["items"]]
        before = page.get("next_before")
        if not before:
            break
    assert len(seen) == 4 and len(set(seen)) == 4


def test_unread_count_is_total_not_page_or_filter(app_client, db_session, as_a):
    ids = _make(db_session, "user_a", 4)
    app_client.post("/me/notifications/read", json={"ids": ids[:1]}, cookies=as_a)
    body = app_client.get("/me/notifications", params={"limit": 1, "unread_only": True}, cookies=as_a).json()
    assert len(body["items"]) == 1 and body["unread_count"] == 3
    assert body["items"][0]["read"] is False
    everything = app_client.get("/me/notifications", cookies=as_a).json()
    assert [i["read"] for i in everything["items"]] == [False, False, False, True]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"limit": "x"}, {"before": "not-a-cursor"}])
def test_list_rejects_bad_query(app_client, as_a, params):
    r = app_client.get("/me/notifications", params=params, cookies=as_a)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


def test_read_some_ids_only(app_client, db_session, as_a):
    ids = _make(db_session, "user_a", 3)
    r = app_client.post("/me/notifications/read", json={"ids": [ids[0], ids[2]]}, cookies=as_a)
    assert r.status_code == 204 and r.content == b""
    items = app_client.get("/me/notifications", cookies=as_a).json()
    assert {i["message"]: i["read"] for i in items["items"]} == {"m0": True, "m1": False, "m2": True}
    assert items["unread_count"] == 1


@pytest.mark.parametrize("body", [None, {}])
def test_read_without_ids_reads_everything(app_client, db_session, as_a, body):
    _make(db_session, "user_a", 3)
    r = app_client.post("/me/notifications/read", **({"json": body} if body is not None else {}), cookies=as_a)
    assert r.status_code == 204
    assert app_client.get("/me/notifications", cookies=as_a).json()["unread_count"] == 0


def test_read_with_empty_ids_reads_nothing(app_client, db_session, as_a):
    _make(db_session, "user_a", 2)
    assert app_client.post("/me/notifications/read", json={"ids": []}, cookies=as_a).status_code == 204
    assert app_client.get("/me/notifications", cookies=as_a).json()["unread_count"] == 2


def test_read_is_idempotent_and_ignores_others_and_unknown_ids(app_client, db_session, as_a, as_b):
    mine = _make(db_session, "user_a", 1)[0]
    theirs = _make(db_session, "user_b", 1)[0]
    body = {"ids": [mine, theirs, str(uuid4()), "not-a-uuid"]}
    assert app_client.post("/me/notifications/read", json=body, cookies=as_a).status_code == 204
    assert app_client.post("/me/notifications/read", json=body, cookies=as_a).status_code == 204   # 두 번째도 같은 결과
    assert app_client.get("/me/notifications", cookies=as_a).json()["unread_count"] == 0
    assert app_client.get("/me/notifications", cookies=as_b).json()["unread_count"] == 1           # 남의 알림은 그대로


def test_read_keeps_the_first_read_time(app_client, db_session, as_a):
    nid = _make(db_session, "user_a", 1)[0]
    app_client.post("/me/notifications/read", json={"ids": [nid]}, cookies=as_a)
    first = db_session.get(Notification, __import__("uuid").UUID(nid)).read_at
    app_client.post("/me/notifications/read", json={"ids": [nid]}, cookies=as_a)
    db_session.expire_all()
    assert db_session.get(Notification, __import__("uuid").UUID(nid)).read_at == first


@pytest.mark.parametrize("body", [{"ids": ["x"] * 101}, {"ids": "abc"}, {"unknown": 1}])
def test_read_rejects_bad_body(app_client, as_a, body):
    r = app_client.post("/me/notifications/read", json=body, cookies=as_a)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


def test_prefs_default_to_all_on_in_declared_order(app_client, as_a):
    r = app_client.get("/me/notification-prefs", cookies=as_a)
    assert r.status_code == 200
    assert r.json() == {"prefs": [{"type": t, "enabled": True} for t in (
        "pin_reaction", "member_joined", "owner_changed", "map_deleted")]}


def test_put_prefs_changes_only_the_sent_types_and_returns_the_whole(app_client, as_a, as_b):
    r = app_client.put("/me/notification-prefs", json={"prefs": [{"type": "pin_reaction", "enabled": False}]}, cookies=as_a)
    assert r.status_code == 200
    assert {p["type"]: p["enabled"] for p in r.json()["prefs"]} == {
        "pin_reaction": False, "member_joined": True, "owner_changed": True, "map_deleted": True}
    r = app_client.put("/me/notification-prefs", json={"prefs": [{"type": "map_deleted", "enabled": False}]}, cookies=as_a)
    assert {p["type"] for p in r.json()["prefs"] if not p["enabled"]} == {"pin_reaction", "map_deleted"}    # 앞의 설정이 남는다
    r = app_client.put("/me/notification-prefs", json={"prefs": [{"type": "pin_reaction", "enabled": True}]}, cookies=as_a)
    assert {p["type"] for p in r.json()["prefs"] if not p["enabled"]} == {"map_deleted"}                    # 다시 켠다
    assert all(p["enabled"] for p in app_client.get("/me/notification-prefs", cookies=as_b).json()["prefs"])  # 남의 설정은 그대로


def test_put_prefs_later_duplicate_wins(app_client, as_a):
    body = {"prefs": [{"type": "pin_reaction", "enabled": False}, {"type": "pin_reaction", "enabled": True}]}
    r = app_client.put("/me/notification-prefs", json=body, cookies=as_a)
    assert r.json()["prefs"][0] == {"type": "pin_reaction", "enabled": True}


@pytest.mark.parametrize("body", [{"prefs": []}, {"prefs": [{"type": "pin_deleted", "enabled": False}]}, {}, {"prefs": [{"type": "pin_reaction"}]}])
def test_put_prefs_rejects_bad_body(app_client, as_a, body):
    r = app_client.put("/me/notification-prefs", json=body, cookies=as_a)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


def test_turning_a_type_off_stops_new_notifications_but_keeps_old_ones(app_client, db_session, as_a):
    _make(db_session, "user_a", 1)
    app_client.put("/me/notification-prefs", json={"prefs": [{"type": "pin_reaction", "enabled": False}]}, cookies=as_a)
    assert api.notify(db_session, user_id="user_a", type="pin_reaction", map_id="m1", map_title=None, message="new") is None
    assert api.notify(db_session, user_id="user_a", type="member_joined", map_id="m1", map_title=None, message="new") is not None
    assert [i["message"] for i in app_client.get("/me/notifications", cookies=as_a).json()["items"]] == ["new", "m0"]

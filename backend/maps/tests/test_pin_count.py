"""Map.pin_count·InviteSummary.pin_count(#313). 센다는 사실만 maps가 알고, 세는 쿼리는
pins.api.count_public_pins_by_map이 한다 — 이 테스트는 그 배선과 응답 모양을 고정한다."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from auth.testing import session_cookie
from pins.models import Pin as PinRow


def _auth(user_id="user_1"):
    return session_cookie(user_id)


def _create_map(app_client, user_id="user_1"):
    resp = app_client.post(
        "/maps",
        json={"title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12"},
        cookies=_auth(user_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _insert_pin(db_session, map_id, *, visibility="public"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility=visibility, created_by="user_1",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_new_map_has_zero_pin_count(app_client):
    assert _create_map(app_client)["pin_count"] == 0


def test_get_map_and_list_show_pin_count_per_map(app_client, db_session):
    a = _create_map(app_client)["id"]
    b = _create_map(app_client)["id"]
    for _ in range(3):
        _insert_pin(db_session, a)
    _insert_pin(db_session, b)

    assert app_client.get(f"/maps/{a}", cookies=_auth()).json()["pin_count"] == 3
    listed = {m["id"]: m["pin_count"] for m in app_client.get("/maps", cookies=_auth()).json()}
    assert listed == {a: 3, b: 1}


def test_deleted_and_private_pins_are_not_counted(app_client, db_session):
    map_id = _create_map(app_client)["id"]
    kept = _insert_pin(db_session, map_id)
    gone = _insert_pin(db_session, map_id)
    _insert_pin(db_session, map_id, visibility="private")
    assert app_client.get(f"/maps/{map_id}", cookies=_auth()).json()["pin_count"] == 2

    gone.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    assert app_client.get(f"/maps/{map_id}", cookies=_auth()).json()["pin_count"] == 1
    assert kept.deleted_at is None


def test_invite_accept_response_has_pin_count(app_client, db_session):
    map_id = _create_map(app_client)["id"]
    _insert_pin(db_session, map_id)
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth()).json()

    resp = app_client.post(f"/invites/{invite['token']}/accept", cookies=_auth("user_2"))
    assert resp.status_code == 200
    assert resp.json()["pin_count"] == 1


def test_invite_summary_has_pin_count_only_without_login(app_client, db_session):
    map_id = _create_map(app_client)["id"]
    _insert_pin(db_session, map_id)
    _insert_pin(db_session, map_id)
    invite = app_client.post(f"/maps/{map_id}/invite", cookies=_auth()).json()

    resp = app_client.get(f"/invites/{invite['token']}")  # 쿠키 없음
    assert resp.status_code == 200
    body = resp.json()
    assert body["pin_count"] == 2
    # 개수만 — 핀 내용·내부 식별자는 없다
    assert set(body) == {
        "title", "start_date", "end_date", "member_count", "pin_count",
        "inviter_display_name", "expires_at",
    }

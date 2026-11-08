"""
지도 색과 대표 이미지(#1445) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
PATCH color, PUT·GET·DELETE /maps/{mapId}/cover, Map의 color·cover_url·owner_display_name, 정리 때 이미지 삭제.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, update

from maps import api, core
from maps.models import Map as MapRow
from maps.models import MapCover
from maps.tests.test_delete_leave_api import _auth, _create_map, _join

WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


def _put(app_client, map_id, data, content_type="image/webp", user_id="user_1"):
    return app_client.put(
        f"/maps/{map_id}/cover", content=data, headers={"Content-Type": content_type}, cookies=_auth(user_id)
    )


def test_owner_sets_and_clears_color_and_others_see_it(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert "color" not in app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()

    resp = app_client.patch(f"/maps/{map_id}", json={"color": "#3D7BF5"}, cookies=_auth("user_1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["color"] == "#3D7BF5"
    assert resp.json()["title"] == "부산 여행"          # 다른 필드는 그대로
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()["color"] == "#3D7BF5"

    # null은 색 지우기 — 다른 필드의 null은 여전히 422
    cleared = app_client.patch(f"/maps/{map_id}", json={"color": None}, cookies=_auth("user_1"))
    assert cleared.status_code == 200, cleared.text
    assert "color" not in cleared.json()
    assert app_client.patch(f"/maps/{map_id}", json={"title": None}, cookies=_auth("user_1")).status_code == 422
    assert app_client.patch(f"/maps/{map_id}", json={"title": "제주", "color": None},
                            cookies=_auth("user_1")).status_code == 200


@pytest.mark.parametrize("color", ["3D7BF5", "#3D7BF", "#3D7BF5A", "#GGGGGG", "red", ""])
def test_color_must_be_hex(app_client, color):
    map_id = _create_map(app_client)
    resp = app_client.patch(f"/maps/{map_id}", json={"color": color}, cookies=_auth("user_1"))
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_member_cannot_change_color(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    assert app_client.patch(f"/maps/{map_id}", json={"color": "#000000"}, cookies=_auth("user_2")).status_code == 403


@pytest.mark.parametrize("data,content_type", [(WEBP, "image/webp"), (PNG, "image/png"), (JPEG, "image/jpeg")])
def test_owner_uploads_and_member_downloads_cover(app_client, data, content_type):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")

    resp = _put(app_client, map_id, data, content_type)
    assert resp.status_code == 200, resp.text
    url = resp.json()["cover_url"]
    assert url.startswith(f"/maps/{map_id}/cover?v=")

    got = app_client.get(url, cookies=_auth("user_2"))
    assert got.status_code == 200
    assert got.content == data
    assert got.headers["content-type"] == content_type
    assert got.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()["cover_url"] == url


def test_replacing_cover_overwrites_and_bumps_version(app_client, db_session):
    map_id = _create_map(app_client)
    assert _put(app_client, map_id, WEBP).status_code == 200
    db_session.execute(update(MapCover).values(updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db_session.commit()
    old_url = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()["cover_url"]

    new_url = _put(app_client, map_id, PNG, "image/png").json()["cover_url"]
    assert new_url != old_url
    assert app_client.get(f"/maps/{map_id}/cover", cookies=_auth("user_1")).content == PNG
    assert db_session.query(MapCover).count() == 1


def test_delete_cover_is_idempotent_and_get_is_404_after(app_client):
    map_id = _create_map(app_client)
    assert app_client.get(f"/maps/{map_id}/cover", cookies=_auth("user_1")).status_code == 404
    _put(app_client, map_id, WEBP)

    for _ in range(2):
        resp = app_client.delete(f"/maps/{map_id}/cover", cookies=_auth("user_1"))
        assert resp.status_code == 200, resp.text
        assert "cover_url" not in resp.json()
    got = app_client.get(f"/maps/{map_id}/cover", cookies=_auth("user_1"))
    assert got.status_code == 404 and got.json()["code"] == "NOT_FOUND"


def test_member_cannot_upload_or_delete_and_outsider_cannot_read(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    _put(app_client, map_id, WEBP)

    assert _put(app_client, map_id, PNG, "image/png", user_id="user_2").status_code == 403
    assert app_client.delete(f"/maps/{map_id}/cover", cookies=_auth("user_2")).status_code == 403
    assert app_client.get(f"/maps/{map_id}/cover", cookies=_auth("user_2")).content == WEBP
    assert app_client.get(f"/maps/{map_id}/cover", cookies=_auth("user_3")).status_code == 404


@pytest.mark.parametrize("data,content_type", [
    (WEBP, "image/gif"),                         # 받지 않는 형식
    (WEBP, None),                                # Content-Type 없음
    (PNG, "image/webp"),                         # 이름표만 webp
    (b"", "image/webp"),                         # 빈 본문
    (WEBP + b"\x00" * core.COVER_MAX_BYTES, "image/webp"),   # 상한 초과
])
def test_invalid_cover_is_cover_invalid_with_policy_detail(app_client, data, content_type):
    map_id = _create_map(app_client)
    headers = {"Content-Type": content_type} if content_type else {}
    resp = app_client.put(f"/maps/{map_id}/cover", content=data, headers=headers, cookies=_auth("user_1"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "COVER_INVALID"
    assert resp.json()["detail"] == {"limit_bytes": core.COVER_MAX_BYTES, "types": ["image/webp", "image/jpeg", "image/png"]}
    assert "cover_url" not in app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()


def test_cover_at_exact_limit_is_accepted(app_client):
    map_id = _create_map(app_client)
    data = WEBP + b"\x00" * (core.COVER_MAX_BYTES - len(WEBP))
    assert _put(app_client, map_id, data).status_code == 200


def test_list_has_cover_url_and_owner_name_without_reading_image_bytes(app_client, test_engine):
    with_cover = _create_map(app_client, title="이미지 있음")
    _create_map(app_client, title="이미지 없음")
    invited = _create_map(app_client, user_id="user_2", title="초대받은 지도")
    _join_as(app_client, invited, inviter="user_2", joiner="user_1")
    _put(app_client, with_cover, WEBP)

    statements = []
    listener = lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt)   # noqa: E731
    event.listen(test_engine, "before_cursor_execute", listener)
    try:
        resp = app_client.get("/maps", cookies=_auth("user_1"))
    finally:
        event.remove(test_engine, "before_cursor_execute", listener)

    items = {m["title"]: m for m in resp.json()["items"]}
    assert items["이미지 있음"]["cover_url"].startswith(f"/maps/{with_cover}/cover?v=")
    assert "cover_url" not in items["이미지 없음"]
    assert items["초대받은 지도"]["owner_display_name"] == "user_2"
    assert items["이미지 있음"]["owner_display_name"] == "user_1"
    cover_queries = [s for s in statements if "map_covers" in s]
    assert len(cover_queries) == 1                       # 지도 수와 무관하게 한 번
    assert "map_covers.data" not in cover_queries[0]     # 바이트는 읽지 않는다


def test_owner_display_name_follows_owner_transfer(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")
    resp = app_client.post(f"/maps/{map_id}/owner", json={"user_id": "user_2"}, cookies=_auth("user_1"))
    assert resp.json()["owner_display_name"] == "user_2"


def test_soft_delete_keeps_cover_and_purge_removes_it(app_client, db_session):
    map_id = _create_map(app_client)
    _put(app_client, map_id, WEBP)
    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    assert db_session.get(MapCover, map_id) is not None              # 복구할 수 있게 남는다
    assert app_client.post(f"/maps/{map_id}/restore", cookies=_auth("user_1")).json()["cover_url"]

    db_session.execute(update(MapRow).where(MapRow.id == map_id).values(deleted_at=datetime.now(timezone.utc)))
    result = api.purge_map_data(db_session, map_ids=[map_id])
    assert result["map_covers"] == 1 and result["maps"] == 1
    assert db_session.query(MapCover).count() == 0


def _join_as(app_client, map_id, *, inviter, joiner):
    token = app_client.post(f"/maps/{map_id}/invite", cookies=_auth(inviter)).json()["token"]
    assert app_client.post(f"/invites/{token}/accept", cookies=_auth(joiner)).status_code == 200

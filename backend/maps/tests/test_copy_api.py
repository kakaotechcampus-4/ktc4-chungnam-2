"""
지도 복사(#1446) 통합 테스트(conftest.py 참고 — 실제 PostgreSQL 필요).
POST /maps/{mapId}/copy — 방장만, 제목 「원래 제목 (n)」, 날짜·지역·색·대표 이미지·공개 핀만 옮긴다.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update

from auth.testing import make_guest
from maps.core import MAP_LIMIT
from maps.models import Membership as MembershipRow
from maps.tests.test_delete_leave_api import _auth, _create_map, _fill_to_limit, _join, _pin, _react
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from shortlist.models import ShortlistItem

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _copy(app_client, map_id, user_id="user_1"):
    return app_client.post(f"/maps/{map_id}/copy", cookies=_auth(user_id))


def test_owner_copies_dates_region_color_cover_and_live_public_pins_only(app_client, db_session):
    resp = app_client.post("/maps", json={
        "title": "부산 여행", "start_date": "2026-10-10", "end_date": "2026-10-12",
        "region": {"label": "부산", "lat": 35.1796, "lng": 129.0756},
    }, cookies=_auth("user_1"))
    map_id = resp.json()["id"]
    _join(app_client, map_id, "user_2")
    assert app_client.patch(f"/maps/{map_id}", json={"color": "#3D7BF5"}, cookies=_auth("user_1")).status_code == 200
    assert app_client.put(f"/maps/{map_id}/cover", content=PNG, headers={"Content-Type": "image/png"},
                          cookies=_auth("user_1")).status_code == 200
    kept = _pin(db_session, map_id, created_by="user_2")
    _react(db_session, kept, "user_2")
    confirmed = _pin(db_session, map_id)
    db_session.execute(update(PinRow).where(PinRow.id == confirmed).values(kind="확정"))
    db_session.add(ShortlistItem(map_id=map_id, pin_id=confirmed, added_by="user_1"))
    trashed = _pin(db_session, map_id)
    db_session.execute(update(PinRow).where(PinRow.id == trashed).values(deleted_at=datetime.now(timezone.utc)))
    db_session.commit()

    resp = _copy(app_client, map_id)

    assert resp.status_code == 201, resp.text
    copied = resp.json()
    assert copied["id"] != map_id
    assert copied["title"] == "부산 여행 (1)"
    assert (copied["start_date"], copied["end_date"]) == ("2026-10-10", "2026-10-12")
    assert copied["region"] == {"label": "부산", "lat": 35.1796, "lng": 129.0756}
    assert copied["color"] == "#3D7BF5"
    assert copied["my_role"] == "owner" and copied["created_by_me"] is True
    assert copied["permissions"]["can_copy"] is True
    assert (copied["member_count"], copied["pin_count"], copied["confirmed_count"]) == (1, 2, 0)

    # 대표 이미지는 새 지도의 주소로 같은 바이트
    assert copied["cover_url"].startswith(f"/maps/{copied['id']}/cover?v=")
    assert app_client.get(copied["cover_url"], cookies=_auth("user_1")).content == PNG

    # 구성원은 복사한 사람 혼자, 다른 구성원에게는 보이지 않는다
    members = db_session.execute(
        select(MembershipRow.user_id, MembershipRow.role).where(MembershipRow.map_id == copied["id"])
    ).all()
    assert [tuple(m) for m in members] == [("user_1", "owner")]
    assert _copy(app_client, copied["id"], "user_2").status_code == 404

    # 핀은 일반 핀으로, 찍은 사람은 복사한 사람, 반응·확정 리스트는 없다
    pins = db_session.execute(select(PinRow).where(PinRow.map_id == copied["id"])).scalars().all()
    assert {(p.kind, p.origin, p.created_by) for p in pins} == {("일반", "direct", "user_1")}
    assert sorted(p.place_id for p in pins) == sorted(
        db_session.execute(select(PinRow.place_id).where(PinRow.id.in_([kept, confirmed]))).scalars()
    )
    assert db_session.execute(select(ReactionRow).where(ReactionRow.pin_id.in_([p.id for p in pins]))).first() is None
    assert db_session.execute(select(ShortlistItem).where(ShortlistItem.map_id == copied["id"])).first() is None

    # 원래 지도는 그대로
    source = app_client.get(f"/maps/{map_id}", cookies=_auth("user_1")).json()
    assert (source["title"], source["pin_count"], source["member_count"], source["confirmed_count"]) == ("부산 여행", 2, 2, 1)


def test_copy_without_region_color_or_cover_leaves_them_empty(app_client):
    map_id = _create_map(app_client)
    copied = _copy(app_client, map_id).json()
    assert {"region", "color", "cover_url"}.isdisjoint(copied)
    assert copied["pin_count"] == 0


def test_title_strips_the_suffix_and_skips_taken_numbers_among_my_live_maps(app_client, db_session):
    map_id = _create_map(app_client, title="제주 (1)")
    _create_map(app_client, title="제주 (2)")
    deleted = _create_map(app_client, title="제주 (3)")
    assert app_client.delete(f"/maps/{deleted}", cookies=_auth("user_1")).status_code == 204   # 삭제한 지도는 세지 않는다
    _create_map(app_client, user_id="user_2", title="제주 (1)")                                 # 남의 지도도 세지 않는다

    first = _copy(app_client, map_id).json()
    assert first["title"] == "제주 (3)"
    assert _copy(app_client, first["id"]).json()["title"] == "제주 (4)"
    assert _copy(app_client, map_id).json()["title"] == "제주 (5)"


def test_member_gets_403_and_outsider_or_deleted_map_404(app_client):
    map_id = _create_map(app_client)
    _join(app_client, map_id, "user_2")

    member = _copy(app_client, map_id, "user_2")
    assert (member.status_code, member.json()["code"]) == (403, "FORBIDDEN")
    assert app_client.get(f"/maps/{map_id}", cookies=_auth("user_2")).json()["permissions"]["can_copy"] is False
    assert _copy(app_client, map_id, "outsider").status_code == 404
    assert len(app_client.get("/maps", cookies=_auth("user_2")).json()["items"]) == 1
    assert app_client.get("/maps", cookies=_auth("outsider")).json()["items"] == []

    assert app_client.delete(f"/maps/{map_id}", cookies=_auth("user_1")).status_code == 204
    assert _copy(app_client, map_id).status_code == 404


def test_copy_over_the_map_limit_is_409(app_client):
    own = _fill_to_limit(app_client, "user_2")
    resp = _copy(app_client, own[0], "user_2")
    assert resp.status_code == 409
    assert resp.json()["code"] == "MAP_LIMIT"
    assert resp.json()["detail"] == {"limit": MAP_LIMIT, "count": MAP_LIMIT}
    assert len(app_client.get("/maps", cookies=_auth("user_2")).json()["items"]) == MAP_LIMIT


def test_guest_owner_cannot_copy(app_client, db_session):
    map_id = _create_map(app_client, user_id="user_guest")   # 만든 뒤 게스트가 된 방장
    make_guest(db_session, "user_guest")
    db_session.commit()
    resp = _copy(app_client, map_id, "user_guest")
    assert (resp.status_code, resp.json()["code"]) == (403, "GUEST_NOT_ALLOWED")
    assert len(app_client.get("/maps", cookies=_auth("user_guest")).json()["items"]) == 1

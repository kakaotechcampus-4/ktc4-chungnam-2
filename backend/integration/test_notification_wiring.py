"""
알림 호출 연결(#470) — pins·maps가 이벤트를 쓰는 같은 트랜잭션에서 notifications.api.notify를 부르는지,
그리고 notify 안의 거르기(본인·끈 종류)와 문장에 사유·메모가 새지 않는 것을 실제 HTTP로 본다.
"""

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    _pin, members, own_db, place_ids, real_client,
)


def _inbox(client) -> list[dict]:
    body = client.get("/me/notifications").json()
    return body["items"]


def test_member_joined_goes_to_the_owner_only(members):
    a, b, _ = members
    items = _inbox(a)
    assert [i["type"] for i in items] == ["member_joined"]
    assert "들어왔어요" in items[0]["message"] and items[0]["map_title"] == "성수"
    assert _inbox(b) == []   # 들어온 사람 본인에게는 없다


def test_reaction_notifies_the_pin_author_without_leaking_the_reason(members, place_ids):
    a, b, m = members
    pin = _pin(a, m, "K", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200
    mine = [i for i in _inbox(a) if i["type"] == "pin_reaction"]
    assert len(mine) == 1 and mine[0]["pin_id"] == pin and "♥" in mine[0]["message"]

    reason = "비밀사유문장"
    assert b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": reason}).status_code == 200
    messages = [i["message"] for i in _inbox(a) if i["type"] == "pin_reaction"]
    assert len(messages) == 2 and any("반대" in text for text in messages)
    assert all(reason not in text for text in messages)   # 반대 사유 원문은 알림에 없다
    assert [i for i in _inbox(b) if i["type"] == "pin_reaction"] == []


def test_own_reaction_and_disabled_type_create_no_notification(members, place_ids):
    a, b, m = members
    pin = _pin(a, m, "K", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200   # 내 핀에 내가
    assert [i for i in _inbox(a) if i["type"] == "pin_reaction"] == []

    off = a.put("/me/notification-prefs", json={"prefs": [{"type": "pin_reaction", "enabled": False}]})
    assert off.status_code == 200
    assert b.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200
    assert [i for i in _inbox(a) if i["type"] == "pin_reaction"] == []   # 끈 종류는 만들지 않는다


def test_reaction_on_a_pin_whose_author_left_creates_no_notification(members, place_ids):
    a, b, m = members
    pin = _pin(b, m, "K", place_ids)
    assert b.delete(f"/maps/{m}/members/me").status_code == 204   # 작성자 b가 지도를 나간다(방장은 a)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200
    assert [i for i in _inbox(b) if i["type"] == "pin_reaction"] == []


def test_direct_hand_over_notifies_the_new_owner_only(members):
    a, b, m = members
    assert a.post(f"/maps/{m}/owner", json={"user_id": "user_b"}).status_code == 200
    assert [i["type"] for i in _inbox(b)] == ["owner_changed"]
    assert [i["type"] for i in _inbox(a)] == ["member_joined"]   # 넘긴 사람에게는 없다


def test_owner_leaving_notifies_the_successor(members):
    a, b, m = members
    assert a.delete(f"/maps/{m}/members/me").status_code == 204
    assert [i["type"] for i in _inbox(b)] == ["owner_changed"]


def test_map_deletion_notifies_the_other_members_with_the_title(members):
    a, b, m = members
    assert a.delete(f"/maps/{m}").status_code == 204
    items = _inbox(b)
    assert [i["type"] for i in items] == ["map_deleted"]
    assert items[0]["map_title"] == "성수" and "성수" in items[0]["message"]
    assert [i["type"] for i in _inbox(a)] == ["member_joined"]   # 삭제한 사람에게는 없다

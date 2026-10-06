"""#369 설계 14번 — 핀 작성자 표시(created_by_display_name)를 조회 시점에 계산한다.
탈퇴했으면 '탈퇴한 구성원'(먼저), 그 지도의 현재 구성원이 아니면 '나간 구성원', 아니면 실명.
현재 구성원 집합은 maps.api.DbMembershipGateway.current_member_ids가 정본이라 maps·memberships 행을 직접 넣는다.
"""

from datetime import date, datetime, timezone

from sqlalchemy import event

from auth.models import User
from auth.testing import ensure_users, session_cookie
from authz.core import Principal
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from pins import api as pins_api
from pins.tests.test_pins_api import _insert_pin


def _make_map(db_session, map_id, members: dict[str, str]):
    db_session.add(MapRow(id=map_id, title=map_id, start_date=date(2026, 11, 1), end_date=date(2026, 11, 3),
                          created_by=next(iter(members))))
    db_session.flush()
    for user_id, role in members.items():
        db_session.add(MembershipRow(map_id=map_id, user_id=user_id, role=role))
    db_session.commit()


def _leave(db_session, map_id, user_id):
    db_session.query(MembershipRow).filter_by(map_id=map_id, user_id=user_id).delete()
    db_session.commit()


def _withdraw(db_session, user_id):
    db_session.get(User, user_id).deleted_at = datetime.now(timezone.utc)
    db_session.commit()


def _names_by_author(client):
    resp = client.get("/maps/map_1/pins", cookies=session_cookie("user_1"))
    assert resp.status_code == 200
    return {p["created_by"]: p.get("created_by_display_name") for p in resp.json()}


def test_list_shows_real_name_left_member_and_withdrawn_member(app_client, db_session):
    ensure_users(db_session, "user_1", "user_2", "user_3",
                 display_names={"user_1": "철수", "user_2": "영희", "user_3": "민수"})
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member", "user_3": "member"})
    for author in ("user_1", "user_2", "user_3"):
        _insert_pin(db_session, created_by=author)
    _leave(db_session, "map_1", "user_2")
    _withdraw(db_session, "user_3")   # 탈퇴자 멤버십 행은 남는다(#245)

    assert _names_by_author(app_client) == {"user_1": "철수", "user_2": "나간 구성원", "user_3": "탈퇴한 구성원"}


def test_withdrawn_after_leaving_is_still_withdrawn(app_client, db_session):
    ensure_users(db_session, "user_1", "user_2", display_names={"user_1": "철수", "user_2": "영희"})
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member"})
    _insert_pin(db_session, created_by="user_2")
    _leave(db_session, "map_1", "user_2")
    _withdraw(db_session, "user_2")

    assert _names_by_author(app_client) == {"user_2": "탈퇴한 구성원"}


def test_rejoining_restores_real_name(app_client, db_session):
    """핀 행에 아무것도 쓰지 않으므로 다시 들어오면 실명으로 돌아간다."""
    ensure_users(db_session, "user_1", "user_2", display_names={"user_1": "철수", "user_2": "영희"})
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member"})
    _insert_pin(db_session, created_by="user_2")
    _leave(db_session, "map_1", "user_2")
    assert _names_by_author(app_client) == {"user_2": "나간 구성원"}

    db_session.add(MembershipRow(map_id="map_1", user_id="user_2", role="member"))
    db_session.commit()
    assert _names_by_author(app_client) == {"user_2": "영희"}


def test_leaving_one_map_does_not_change_pins_on_another_map(app_client, db_session):
    """단건 조회(shortlist·recommend가 쓰는 pins.api.get_pin_response_for_viewer)도 같은 판정을 쓴다."""
    ensure_users(db_session, "user_1", "user_2", display_names={"user_1": "철수", "user_2": "영희"})
    _make_map(db_session, "map_1", {"user_1": "owner", "user_2": "member"})
    _make_map(db_session, "map_2", {"user_1": "owner", "user_2": "member"})
    pin_1 = _insert_pin(db_session, map_id="map_1", created_by="user_2")
    pin_2 = _insert_pin(db_session, map_id="map_2", created_by="user_2")
    _leave(db_session, "map_1", "user_2")

    def single(pin, map_id):
        principal = Principal(user_id="user_1", map_id=map_id, role="owner")
        return pins_api.get_pin_response_for_viewer(
            db_session, pin_id=str(pin.id), viewer_id="user_1", principal=principal,
        ).created_by_display_name

    assert single(pin_1, "map_1") == "나간 구성원"
    assert single(pin_2, "map_2") == "영희"


def test_list_query_count_does_not_grow_with_pins(app_client, db_session):
    """작성자 판정(이름·탈퇴·현재 구성원)이 핀마다 쿼리하지 않는다 — 핀 1개와 5개의 쿼리 수가 같다."""
    authors = [f"user_q{i}" for i in range(5)]
    ensure_users(db_session, "user_1", *authors)
    _make_map(db_session, "map_1", {"user_1": "owner", **{a: "member" for a in authors}})
    _leave(db_session, "map_1", authors[1])
    _withdraw(db_session, authors[2])

    def count_queries():
        statements = []
        engine = db_session.get_bind().engine

        def on_execute(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", on_execute)
        try:
            _names_by_author(app_client)
        finally:
            event.remove(engine, "before_cursor_execute", on_execute)
        return len(statements)

    _insert_pin(db_session, created_by=authors[0])
    with_one = count_queries()
    for author in authors[1:]:
        _insert_pin(db_session, created_by=author)
    with_five = count_queries()

    assert with_one == with_five
    names = _names_by_author(app_client)
    assert names[authors[1]] == "나간 구성원" and names[authors[2]] == "탈퇴한 구성원"

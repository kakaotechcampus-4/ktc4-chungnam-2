"""#1564 — Pin.neighborhood: 자체 DB 장소 주소에서 places.core.neighborhood와 같은 규칙. live·주소 없음은 필드 생략."""

from sqlalchemy import event

from places import api as places_api
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth

ADDRESS = "서울특별시 성동구 성수동2가 (성수동2가) 1-1"


def _row(fake_places, key):
    return next(r for r in fake_places.rows if r.key == key)


def _post(app_client, body):
    return app_client.post("/maps/map_1/pins", json=body, cookies=_auth())


def test_db_pin_has_the_neighborhood_in_create_list_and_detail(app_client, fake_places):
    _row(fake_places, "seongsu-kalguksu").address = "서울특별시 성동구 성수이로 1 (성수동2가)"
    created = _post(app_client, KALGUKSU).json()
    expected = places_api.neighborhood("서울특별시 성동구 성수이로 1 (성수동2가)")
    assert expected == "성동구 성수동2가" and created["neighborhood"] == expected
    listed = app_client.get("/maps/map_1/pins", cookies=_auth()).json()
    assert listed[0]["neighborhood"] == expected
    assert "neighborhood" not in _post(app_client, CAFE).json()    # 주소 없는 장소는 필드가 없다


def test_live_pin_has_no_neighborhood(app_client):
    live = {"source": "live", "category": "음식점", "kakao_place_id": "kakao:777", "search_query": "성수 곱창"}
    assert "neighborhood" not in _post(app_client, live).json()
    assert "neighborhood" not in app_client.get("/maps/map_1/pins", cookies=_auth()).json()[0]


def test_list_query_count_does_not_grow_with_pins(app_client, db_session, fake_places):
    _row(fake_places, "seongsu-kalguksu").address = "서울특별시 성동구 성수이로 1 (성수동2가)"
    _row(fake_places, "seongsu-cafe-a").address = "서울특별시 성동구 아차산로 2 (성수동1가)"
    engine = db_session.get_bind().engine
    statements: list[str] = []

    def on_execute(conn, cursor, statement, *args):
        statements.append(statement)

    def list_count():
        statements.clear()
        event.listen(engine, "before_cursor_execute", on_execute)
        try:
            assert app_client.get("/maps/map_1/pins", cookies=_auth()).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", on_execute)
        return len(statements)

    _post(app_client, KALGUKSU)
    one = list_count()
    _post(app_client, CAFE)
    assert list_count() == one          # 핀이 늘어도 쿼리 수는 같다 — 장소 배치 조회에 얹었다

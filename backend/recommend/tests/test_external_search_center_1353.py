"""카카오맵 검색 링크의 동네가 보고 있는 곳(center) 근처여야 한다(#1353).

readiness는 center(`center_lat`·`center_lng`)가 핀과 멀면 보고 있는 곳과 다른 동네를 가리켰다(핀 주소·지도 지역 기준). 이제 center가 있으면
center 근처의 가장 가까운 영업 중 자체 DB 장소(분류 무관)의 주소에서 동네를 뽑는다. 그 안에 장소가 없으면 시·도 이름, 그것도 없으면 지금의 핀·지도
지역 기준 이름이다. center가 없는 호출은 지금 그대로다. 카카오 같은 외부 호출은 늘지 않는다(자체 DB만 읽는다, #53)."""

import contextlib
import socket

import pytest
from sqlalchemy import event

from places.models import Place
from recommend import flows
from recommend.models import RecommendRun
from recommend.tests.test_external_search import CATEGORY, CATEGORY_WORD, _info, _Places, _search
from recommend.tests.test_flows import _make_members, _make_pin, _react
from recommend.tests.test_outside_trip_region_1385 import _boundary, _square

HAEUNDAE = (35.1587, 129.1604)           # 부산 해운대 — 핀(서울)과 멀다
SEOUL_PIN_AREA_QUERY = f"성동구 성수동2가 {CATEGORY_WORD}"   # 핀 주소 기준(지금 동작): _info의 기본 주소


def _place(db, source_id, lat, lng, address, *, category="카페", status="open"):
    place = Place(source="permit", source_id=source_id, name=f"가게{source_id}", category=category, address=address, status=status,
                  geom=f"SRID=4326;POINT({lng} {lat})")
    db.add(place)
    db.flush()
    return place


@contextlib.contextmanager
def _places_queries(db):
    """블록 안에서 places 테이블을 읽는 SQL 문장을 모은다(조회 횟수를 센다)."""
    statements: list[str] = []
    connection = db.get_bind()

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM places" in statement:
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _north(lat, meters):
    return lat + meters / 111_195


@pytest.fixture
def seoul_pin(db_session):
    """서울(성수동2가) 핀 하나에 의견이 있는 지도 — 핀 기준 이름이면 「성동구 성수동2가」다. 근처 정예 수는 0이라 검색 링크가 나온다."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category=CATEGORY)
    _react(db_session, pin, user_id="user_1")
    places = _Places(infos=[_info(pin.place_id)], curated=0)
    return db_session, places


def _external(db, places, **kwargs):
    return flows.get_readiness(db, map_id="map_1", place_search=places, **kwargs)[CATEGORY]["external_search"]


def test_center_far_from_the_pin_gives_the_neighborhood_near_the_center(seoul_pin):
    db, places = seoul_pin
    _place(db, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")

    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 우동 {CATEGORY_WORD}")   # 핀(서울)이 아니라 해운대 쪽
    assert _external(db, places) == _search(SEOUL_PIN_AREA_QUERY)                               # center가 없으면 지금 동작 그대로


def test_the_nearest_place_wins_any_category_counts_and_a_missing_address_falls_to_the_next(seoul_pin):
    db, places = seoul_pin
    _place(db, "far", _north(HAEUNDAE[0], 3000), HAEUNDAE[1], "부산광역시 수영구 광안로 1 (광안동)", category="음식점")   # 약 3km
    _place(db, "near-no-address", _north(HAEUNDAE[0], 300), HAEUNDAE[1], "", category="관광지")                       # 가장 가깝지만 주소가 없다
    _place(db, "near", _north(HAEUNDAE[0], 800), HAEUNDAE[1], "부산광역시 해운대구 달맞이길 1 (중동)", category="카페")      # 분류가 달라도 센다

    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 중동 {CATEGORY_WORD}")


def test_a_place_within_10km_counts(seoul_pin):
    db, places = seoul_pin
    _place(db, "nine", _north(HAEUNDAE[0], 9000), HAEUNDAE[1], "부산광역시 기장군 정관읍 1 (모전리)")
    # 동네 이름 규칙은 places.core.neighborhood 그대로다 — 괄호 안이 「리」면 동으로 보지 않아 시·군·구까지만 나온다
    assert _external(db, places, center=HAEUNDAE) == _search(f"기장군 {CATEGORY_WORD}")


def test_without_a_place_within_10km_it_falls_back_to_the_sido_then_to_the_pin_name(seoul_pin):
    db, places = seoul_pin
    _place(db, "twelve", _north(HAEUNDAE[0], 12000), HAEUNDAE[1], "부산광역시 기장군 장안읍 1 (장안리)")   # 10km 밖

    # 근처 장소도 경계 데이터도 없으면 지금처럼 핀 기준 이름(되돌아가기 끝)
    assert _external(db, places, center=HAEUNDAE) == _search(SEOUL_PIN_AREA_QUERY)

    # 시·도 경계가 있으면 경계로 정한 시·도 이름
    _boundary(db, "21", "부산", [[_square(35.0, 129.0, 35.3, 129.3)]])
    assert _external(db, places, center=HAEUNDAE) == _search(f"부산 {CATEGORY_WORD}")


def test_a_nearby_place_wins_over_the_sido_name(seoul_pin):
    db, places = seoul_pin
    _boundary(db, "21", "부산", [[_square(35.0, 129.0, 35.3, 129.3)]])
    _place(db, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")
    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 우동 {CATEGORY_WORD}")


def test_in_the_middle_of_the_sea_with_nothing_around_it_keeps_the_old_name(seoul_pin):
    db, places = seoul_pin
    assert _external(db, places, center=(35.0, 131.0)) == _search(SEOUL_PIN_AREA_QUERY)   # 바다 위: 장소도 경계도 없다


def test_no_external_call_is_made_only_the_own_database_is_read(seoul_pin, monkeypatch):
    """카카오 같은 외부 호출을 늘리지 않는다 — 새 소켓 연결이 하나라도 있으면 실패한다(DB는 libpq라 파이썬 소켓을 쓰지 않는다)."""
    db, places = seoul_pin
    _place(db, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")

    def refuse(*args, **kwargs):
        raise AssertionError("외부 연결을 시도했다")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 우동 {CATEGORY_WORD}")
    assert places.curated_circles   # 정예 수는 게이트웨이(자체 DB)로 셌다


def test_the_result_screens_link_uses_the_runs_requested_center(seoul_pin):
    """결과 화면의 검색 링크(`_run_external_search`)도 요청한 중심 근처다. 중심이 없는 옛 run은 핀 기준 그대로다."""
    db, places = seoul_pin
    _place(db, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")
    with_origin = RecommendRun(map_id="map_1", category=CATEGORY, requested_by="user_1", status="done",
                               origin_lat=HAEUNDAE[0], origin_lng=HAEUNDAE[1])
    old_run = RecommendRun(map_id="map_1", category=CATEGORY, requested_by="user_1", status="done")

    assert flows._run_external_search(db, with_origin, places).model_dump() == _search(f"해운대구 우동 {CATEGORY_WORD}")
    assert flows._run_external_search(db, old_run, places).model_dump() == _search(SEOUL_PIN_AREA_QUERY)


# ---------------------------------------------------------------- 검수 반영: 주소 없는 장소, 동률, 폐업, 10km 경계, 조회 횟수, 실제 places 경로

def test_many_nearer_places_without_an_address_do_not_hide_a_valid_one_within_10km(seoul_pin):
    """앞의 5개가 아니라 가까운 순서대로 **동네를 뽑을 수 있는 첫 장소**를 찾는다 — 주소 없는 가까운 장소가 7곳이어도 8번째(900m)를 쓴다."""
    db, places = seoul_pin
    for i in range(7):
        _place(db, f"blank{i}", _north(HAEUNDAE[0], 100 + 100 * i), HAEUNDAE[1], "", category=("음식점", "카페", "관광지")[i % 3])
    _place(db, "eighth", _north(HAEUNDAE[0], 900), HAEUNDAE[1], "부산광역시 해운대구 달맞이길 1 (중동)")
    _place(db, "far", _north(HAEUNDAE[0], 5000), HAEUNDAE[1], "부산광역시 기장군 일광읍 1 (삼성리)")

    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 중동 {CATEGORY_WORD}")


def test_addresses_are_read_in_chunks_only_when_the_nearest_ones_have_none(seoul_pin):
    """주소 조회는 가까운 순서의 묶음(50곳)이다 — 앞 묶음이 모두 비어 있으면 다음 묶음을 읽는다(56번째 장소를 찾는다)."""
    db, places = seoul_pin
    for i in range(55):
        _place(db, f"blank{i:02d}", _north(HAEUNDAE[0], 50 + 10 * i), HAEUNDAE[1], "")
    _place(db, "valid", _north(HAEUNDAE[0], 1000), HAEUNDAE[1], "부산광역시 수영구 광안해변로 1 (광안동)")

    with _places_queries(db) as queries:
        assert flows._area_near_center(db, HAEUNDAE) == "수영구 광안동"
    # 분류별 공간 조회 3번 + 주소 묶음 2번(50곳 + 6곳)
    assert len(queries) == 5


def test_two_places_at_the_same_distance_are_ordered_by_place_id(seoul_pin):
    db, places = seoul_pin
    first = _place(db, "tie-a", *HAEUNDAE, "부산광역시 해운대구 우동로 1 (우동)")
    second = _place(db, "tie-b", *HAEUNDAE, "부산광역시 해운대구 중동로 1 (중동)")
    by_id = {str(first.id): "해운대구 우동", str(second.id): "해운대구 중동"}

    assert _external(db, places, center=HAEUNDAE) == _search(f"{by_id[min(by_id)]} {CATEGORY_WORD}")   # 거리가 같으면 place_id가 작은 곳


def test_a_closed_place_is_never_used(seoul_pin):
    db, places = seoul_pin
    _place(db, "closed", *HAEUNDAE, "부산광역시 해운대구 우동로 1 (우동)", status="closed")   # 가장 가깝지만 폐업
    _place(db, "open", _north(HAEUNDAE[0], 2000), HAEUNDAE[1], "부산광역시 해운대구 중동로 1 (중동)")
    assert _external(db, places, center=HAEUNDAE) == _search(f"해운대구 중동 {CATEGORY_WORD}")


def test_the_10km_edge_inside_is_used_and_outside_is_not(seoul_pin):
    db, places = seoul_pin
    _place(db, "inside", _north(HAEUNDAE[0], 9900), HAEUNDAE[1], "부산광역시 기장군 정관읍 1 (용수리)")
    assert flows._area_near_center(db, HAEUNDAE) == "기장군"
    db.execute(Place.__table__.delete())   # 안쪽 장소를 지우고 바깥쪽(10.1km)만 둔다
    _place(db, "outside", _north(HAEUNDAE[0], 10100), HAEUNDAE[1], "부산광역시 기장군 정관읍 1 (용수리)")
    assert flows._area_near_center(db, HAEUNDAE) is None   # 경계 데이터도 없다


def test_the_places_table_is_read_once_per_category_plus_one_shared_address_read(seoul_pin):
    """readiness는 0곳인 분류마다 검색 링크를 만들지만 같은 center의 동네는 한 번만 계산한다 — 공간 조회 3번(분류당 1번) + 주소 1번 = 4번.
    (분류마다 따로 계산하면 12번이다.)"""
    db, places = seoul_pin
    _place(db, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")

    with _places_queries(db) as shared:
        readiness = flows.get_readiness(db, map_id="map_1", place_search=places, center=HAEUNDAE)
    assert len(shared) == 4
    queries = {category: readiness[category]["external_search"]["query"] for category in readiness}
    assert all(query.startswith("해운대구 우동 ") for query in queries.values()) and len(queries) == 3   # 세 분류 모두 같은 동네, 분류 말만 다르다

    with _places_queries(db) as alone:
        flows._area_near_center(db, HAEUNDAE)
    assert len(alone) == 4   # 한 번 계산하는 데 드는 조회 수(3 + 1)


# ---------------------------------------------------------------- 가짜 대역 없이 실제 places 경로, 소켓 차단

@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("외부 연결을 시도했다")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_the_real_places_path_makes_no_network_call_on_the_success_path(db_session, no_network):
    """`search_nearby_own`·`get_places`·`neighborhood` — 게이트웨이 가짜 없이 실제 places.api 함수만 부른다."""
    _place(db_session, "hae1", *HAEUNDAE, "부산광역시 해운대구 해운대로 1 (우동)")
    assert flows._area_near_center(db_session, HAEUNDAE) == "해운대구 우동"


def test_the_real_places_path_makes_no_network_call_on_the_sido_fallback_path(db_session, no_network):
    """근처 장소가 없어 `sido_at`(경계 표)으로 되돌아가는 길도 외부 호출이 없다. 그것도 못 정하면(바다) None이다."""
    _boundary(db_session, "21", "부산", [[_square(35.0, 129.0, 35.3, 129.3)]])
    assert flows._area_near_center(db_session, HAEUNDAE) == "부산"
    assert flows._area_near_center(db_session, (35.0, 131.5)) is None

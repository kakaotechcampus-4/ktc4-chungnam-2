"""검색 결과의 카카오맵 링크(#1486) — 자체 DB 장소 결과(이름 검색·근처 찾기·링크 해석)의 place_source.url은
기록된 카카오 URL이 있으면 그것, 없으면 「이름 동네」 카카오맵 검색 링크다. 실제 PostgreSQL+PostGIS.
기대값은 구현 함수가 아니라 리터럴로 적는다."""

from urllib.parse import unquote

import pytest
from sqlalchemy import event, func

from places import api
from places.models import Place

SEARCH_PREFIX = "https://map.kakao.com/link/search/"
RECORDED = "https://place.map.kakao.com/555"


def _add(db, sid, name, address, *, kakao_place_id=None, kakao_place_url=None, source="permit", lng=127.0557, lat=37.5445):
    p = Place(source=source, source_id=sid, name=name, category="음식점", address=address, status="open",
              kakao_place_id=kakao_place_id, kakao_place_url=kakao_place_url,
              geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326))
    db.add(p)
    db.flush()
    return p


def _search_query(url: str) -> str:
    assert url.startswith(SEARCH_PREFIX), url
    return unquote(url[len(SEARCH_PREFIX):])


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from places.ratelimit import SlidingWindowLimiter

    monkeypatch.setattr(api, "search_limiter", SlidingWindowLimiter(1000))


def _two_places(db):
    _add(db, "1", "성수 칼국수", "서울특별시 성동구 성수이로 100 (성수동1가)", kakao_place_id="kakao:555", kakao_place_url=RECORDED)
    _add(db, "2", "성수 만두", "서울특별시 성동구 성수이로 120 (성수동2가)", source="tourapi", lng=127.0558)


def test_name_search_fills_the_recorded_url_or_a_search_link(db_session):
    _two_places(db_session)
    by_name = {h.result.place_name: h.result for h in api.search_own_for_query("성수", None, 10, db=db_session)}
    assert by_name["성수 칼국수"].place_source.url == RECORDED
    assert by_name["성수 칼국수"].place_source.provider == "permit"
    assert _search_query(by_name["성수 만두"].place_source.url) == "성수 만두 성동구 성수동2가"
    assert by_name["성수 만두"].place_source.provider == "tourapi"


def test_nearby_search_fills_the_recorded_url_or_a_search_link(db_session):
    _two_places(db_session)
    by_name = {r.place_name: r for r in api.nearest_own_places(37.5445, 127.0557, None, db=db_session)}
    assert by_name["성수 칼국수"].place_source.url == RECORDED
    assert _search_query(by_name["성수 만두"].place_source.url) == "성수 만두 성동구 성수동2가"
    assert by_name["성수 만두"].place_source.provider == "tourapi"


def test_link_match_fills_provider_and_the_recorded_url(db_session):
    _two_places(db_session)
    r = api.parse_link("https://place.map.kakao.com/555", db=db_session)
    assert [m.place_name for m in r.matches] == ["성수 칼국수"]
    assert r.matches[0].place_source.url == RECORDED and r.matches[0].place_source.provider == "permit"


def test_link_match_without_a_recorded_url_gets_a_search_link(db_session):
    p = _add(db_session, "3", "성수 칼국수", "서울특별시 성동구 성수이로 100 (성수동1가)")
    api.record_external_id("naver", "naver:1412566798", str(p.id), source="hint", db=db_session)
    r = api.parse_link("https://map.naver.com/p/entry/place/1412566798", db=db_session)
    assert [m.place_name for m in r.matches] == ["성수 칼국수"]
    assert _search_query(r.matches[0].place_source.url) == "성수 칼국수 성동구 성수동1가"
    assert r.matches[0].place_source.provider == "permit"


def test_a_place_without_a_name_area_falls_back_to_the_name_only(db_session):
    _add(db_session, "4", "성수 국밥", None)
    [hit] = api.search_own_for_query("성수 국밥", None, 10, db=db_session)
    assert _search_query(hit.result.place_source.url) == "성수 국밥"


def test_more_results_do_not_add_queries(db_session):
    def count_queries(query):
        seen = []
        engine = db_session.get_bind()
        listener = lambda conn, cursor, statement, *a: seen.append(statement)
        event.listen(engine, "before_cursor_execute", listener)
        try:
            api.search_own_for_query(query, None, 10, db=db_session)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    _add(db_session, "10", "별미 국수", "서울특별시 성동구 성수이로 1 (성수동1가)")
    one = count_queries("별미")
    for i in range(11, 18):
        _add(db_session, str(i), f"별미 국수 {i}", "서울특별시 성동구 성수이로 1 (성수동1가)", lng=127.0557 + i * 0.0001)
    assert count_queries("별미") == one   # 결과가 8곳으로 늘어도 쿼리 수는 같다(열만 하나 더 읽는다)

"""#577 — 카톡 대화 링크 일괄 핀 찍기: POST /maps/{mapId}/pins/link-preview, /pins/bulk.

대화 원문은 서버로 오지 않고(URL만), 모델도 부르지 않는다. URL·좌표·이름은 응답과 로그에 남지 않는다.
parse_link는 대역으로 바꾼다(실제 해석은 places 테스트가 담당) — 여기서는 병렬·마감·이미 있음 표시·일괄 생성을 본다.
"""

import logging
import threading
import time

import pytest
from sqlalchemy import select

from common.errors import AppError
from common.ratelimit import SlidingWindowLimiter
from pins import link_import, service
from pins.models import Pin as PinRow
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth, _events
from places.schemas import LinkParseResult, PlaceSearchResult

LIVE = {"source": "live", "category": "음식점", "kakao_place_id": "kakao:555", "search_query": "성수 곱창"}
SECRET_URL = "https://maps.app.goo.gl/SECRETtoken123"


def _preview(app_client, urls, user="user_1", map_id="map_1"):
    return app_client.post(f"/maps/{map_id}/pins/link-preview", json={"urls": urls}, cookies=_auth(user))


def _bulk(app_client, pins, user="user_1", map_id="map_1"):
    return app_client.post(f"/maps/{map_id}/pins/bulk", json={"pins": pins}, cookies=_auth(user))


def _match(place_id, name="성수 칼국수"):
    return PlaceSearchResult(place_id=place_id, place_name=name, lat=37.5445, lng=127.0561, category="음식점", pinnable=True)


def _stub_parse(monkeypatch, table):
    """url -> LinkParseResult | 예외 | callable. 모르는 url은 LINK_NOT_SUPPORTED."""
    def parse(url, *, db=None):
        value = table.get(url, AppError("LINK_NOT_SUPPORTED"))
        value = value() if callable(value) else value
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr("places.api.parse_link", parse)


# ---- link-preview ----

def test_items_keep_order_and_failures_do_not_fail_the_request(app_client, monkeypatch):
    ok = LinkParseResult(provider="kakao", kakao_place_id="kakao:777", matches=[], needs_search_query=True)
    _stub_parse(monkeypatch, {"u0": ok, "u1": AppError("LINK_NOT_SUPPORTED"), "u2": AppError("LINK_UNRESOLVED"), "u3": RuntimeError("boom")})
    resp = _preview(app_client, ["u0", "u1", "u2", "u3"])
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["index"] for i in items] == [0, 1, 2, 3]
    assert [i["status"] for i in items] == ["ok", "error", "error", "error"]
    assert items[0]["result"]["kakao_place_id"] == "kakao:777" and items[0]["result"]["needs_search_query"] is True
    assert [i.get("error_code") for i in items[1:]] == ["LINK_NOT_SUPPORTED", "LINK_UNRESOLVED", "LINK_UNRESOLVED"]
    assert all("already_pinned_pin_id" not in i for i in items)


def test_already_pinned_by_own_db_pin_live_pin_and_kakao_id(app_client, fake_places, monkeypatch):
    db_pin = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()   # 카카오 ID가 자체 DB 장소에 기록된다
    live_pin = app_client.post("/maps/map_1/pins", json=LIVE, cookies=_auth()).json()
    own_id = fake_places.place_id("seongsu-kalguksu")
    cafe_id = fake_places.place_id("seongsu-cafe-a")
    _stub_parse(monkeypatch, {
        "own": LinkParseResult(provider="google", name_hint="성수 칼국수", matches=[_match(f"own:{own_id}")], needs_search_query=False),
        "recorded": LinkParseResult(provider="kakao", kakao_place_id="kakao:1001", matches=[_match("kakao:1001")], needs_search_query=False),
        "live": LinkParseResult(provider="kakao", kakao_place_id="kakao:555", matches=[], needs_search_query=True),
        "new": LinkParseResult(provider="google", matches=[_match(f"own:{cafe_id}", "온도 커피")], needs_search_query=False),
    })
    items = _preview(app_client, ["own", "recorded", "live", "new"]).json()["items"]
    assert [i.get("already_pinned_pin_id") for i in items] == [db_pin["id"], db_pin["id"], live_pin["id"], None]


def test_already_pinned_is_per_map(app_client, db_session, monkeypatch):
    db_session.add(PinRow(
        map_id="map_2", category="음식점", kind="일반", origin="direct", source="live", visibility="public",
        created_by="user_1", kakao_place_id="kakao:555", search_query="다른 지도"))
    db_session.commit()
    _stub_parse(monkeypatch, {"live": LinkParseResult(provider="kakao", kakao_place_id="kakao:555", matches=[], needs_search_query=True)})
    assert "already_pinned_pin_id" not in _preview(app_client, ["live"]).json()["items"][0]


def test_links_are_parsed_in_parallel(app_client, monkeypatch):
    slow = lambda: (time.sleep(0.4), LinkParseResult(provider="kakao", matches=[], needs_search_query=True))[1]
    _stub_parse(monkeypatch, {f"u{i}": slow for i in range(5)})
    started = time.monotonic()
    resp = _preview(app_client, [f"u{i}" for i in range(5)])
    assert resp.status_code == 200 and all(i["status"] == "ok" for i in resp.json()["items"])
    assert time.monotonic() - started < 1.2   # 직렬이면 2초


def test_items_past_the_deadline_become_link_unresolved(app_client, monkeypatch):
    release = threading.Event()
    fast = LinkParseResult(provider="kakao", matches=[], needs_search_query=True)
    _stub_parse(monkeypatch, {"fast": fast, "slow": lambda: (release.wait(5), fast)[1]})
    monkeypatch.setattr(link_import, "PREVIEW_DEADLINE_S", 0.3)
    try:
        started = time.monotonic()
        items = _preview(app_client, ["fast", "slow", "fast"]).json()["items"]
        assert time.monotonic() - started < 2
    finally:
        release.set()
    assert [i["status"] for i in items] == ["ok", "error", "ok"]
    assert items[1]["error_code"] == "LINK_UNRESOLVED"


def test_rate_limit_counts_urls_and_rejects_the_whole_request(app_client, monkeypatch):
    monkeypatch.setattr(link_import, "link_preview_limiter", SlidingWindowLimiter(5))
    _stub_parse(monkeypatch, {})
    assert _preview(app_client, ["a", "b", "c"]).status_code == 200
    over = _preview(app_client, ["a", "b", "c"])
    assert over.status_code == 429 and over.json()["code"] == "RATE_LIMITED"
    assert _preview(app_client, ["a", "b"]).status_code == 200            # 거절된 요청은 세지 않는다
    assert _preview(app_client, ["a"]).status_code == 429
    assert _preview(app_client, ["a"], user="user_2").status_code == 200   # 사용자별


@pytest.mark.parametrize("urls", [[], ["x"] * 11, ["가" * 2001], [""]])
def test_malformed_request_is_422(app_client, urls):
    assert _preview(app_client, urls).status_code == 422


def test_non_member_is_404(app_client, monkeypatch):
    _stub_parse(monkeypatch, {})
    assert _preview(app_client, ["a"], user="outsider").status_code == 404


def test_extra_fields_are_422(app_client, monkeypatch):
    _stub_parse(monkeypatch, {})
    assert app_client.post("/maps/map_1/pins/link-preview", json={"urls": ["a"], "text": "대화"}, cookies=_auth()).status_code == 422


def test_url_is_never_in_the_response_or_logs(app_client, monkeypatch, caplog):
    result = LinkParseResult(provider="google", name_hint="성수 칼국수", matches=[_match("own:abc")], needs_search_query=False)
    _stub_parse(monkeypatch, {SECRET_URL: result, SECRET_URL + "/bad": RuntimeError(SECRET_URL), SECRET_URL + "/x": AppError("LINK_UNRESOLVED")})
    with caplog.at_level(logging.DEBUG):
        resp = _preview(app_client, [SECRET_URL, SECRET_URL + "/bad", SECRET_URL + "/x"])
    assert resp.status_code == 200
    assert "SECRET" not in resp.text and '"url"' not in resp.text
    assert "SECRET" not in caplog.text and "37.5445" not in caplog.text and "성수 칼국수" not in caplog.text


# ---- bulk ----

def test_bulk_creates_each_item_and_reports_duplicates_and_rejections(app_client, db_session):
    existing = app_client.post("/maps/map_1/pins", json=KALGUKSU, cookies=_auth()).json()
    nowhere = {**CAFE, "place_id": "kakao:404", "place_name": "없는 가게", "lat": 35.0, "lng": 129.0}
    resp = _bulk(app_client, [CAFE, KALGUKSU, nowhere, {"category": "음식점"}, {**LIVE, "category": "숙소"}, LIVE])
    assert resp.status_code == 200, resp.text
    r = resp.json()["results"]
    assert [x["index"] for x in r] == list(range(6))
    assert [x["status"] for x in r] == ["created", "duplicate", "rejected", "rejected", "rejected", "created"]
    assert r[0]["pin"]["place_name"] == "온도 커피 성수" and r[0]["pin"]["permissions"]["can_edit"] is True
    assert r[1]["error"]["code"] == "PIN_DUPLICATE" and r[1]["error"]["detail"]["pin_id"] == existing["id"]
    assert r[2]["error"]["code"] == "PLACE_NOT_SUPPORTED"
    assert r[3]["error"]["code"] == "VALIDATION_ERROR" and r[4]["error"]["code"] == "VALIDATION_ERROR"
    assert r[5]["pin"]["source"] == "live"
    assert len(app_client.get("/maps/map_1/pins", cookies=_auth()).json()) == 3
    assert len(_events(db_session, type="pin.created")) == 3   # 기존 1 + 만들어진 2


def test_same_place_twice_in_one_request_second_is_duplicate(app_client):
    r = _bulk(app_client, [KALGUKSU, KALGUKSU, LIVE, {**LIVE}]).json()["results"]
    assert [x["status"] for x in r] == ["created", "duplicate", "created", "duplicate"]
    assert r[1]["error"]["detail"]["pin_id"] == r[0]["pin"]["id"] and r[3]["error"]["detail"]["pin_id"] == r[2]["pin"]["id"]


def test_cross_duplicate_between_live_and_db_inside_a_batch(app_client):
    r = _bulk(app_client, [{**LIVE, "kakao_place_id": "kakao:1001"}, KALGUKSU]).json()["results"]   # 같은 가게를 live·search로
    assert [x["status"] for x in r] == ["created", "duplicate"] and r[1]["error"]["detail"]["pin_id"] == r[0]["pin"]["id"]


def test_race_on_unique_index_rolls_back_only_that_item(app_client, db_session, monkeypatch):
    """사전 조회가 놓친 중복(동시 요청)이 유니크 인덱스에 걸려도 앞서 만든 항목은 남는다 — db.rollback() 금지."""
    real = service._find_existing_pin_id
    calls = {"n": 0}

    def blind_to_second_precheck(db, map_id, place_id):
        calls["n"] += 1
        return None if calls["n"] == 2 else real(db, map_id, place_id)   # 둘째 항목의 사전 조회 한 번만 놓친다

    first = _bulk(app_client, [KALGUKSU]).json()["results"][0]["pin"]
    monkeypatch.setattr(service, "_find_existing_pin_id", blind_to_second_precheck)
    r = _bulk(app_client, [CAFE, KALGUKSU]).json()["results"]
    assert [x["status"] for x in r] == ["created", "duplicate"]
    assert r[1]["error"]["detail"]["pin_id"] == first["id"]
    db_session.expire_all()
    assert len(db_session.execute(select(PinRow).where(PinRow.map_id == "map_1", PinRow.deleted_at.is_(None))).scalars().all()) == 2


@pytest.mark.parametrize("pins", [[], [LIVE] * 31])
def test_bulk_size_limits_are_422(app_client, pins):
    assert _bulk(app_client, pins).status_code == 422


def test_bulk_thirty_is_allowed(app_client):
    pins = [{**LIVE, "kakao_place_id": f"kakao:{9000 + i}"} for i in range(30)]
    r = _bulk(app_client, pins).json()["results"]
    assert len(r) == 30 and all(x["status"] == "created" for x in r)


def test_bulk_non_member_is_404_and_changes_nothing(app_client, db_session):
    assert _bulk(app_client, [KALGUKSU], user="outsider").status_code == 404
    assert db_session.execute(select(PinRow)).scalars().all() == []


def test_bulk_does_not_log_hints(app_client, caplog):
    with caplog.at_level(logging.DEBUG):
        resp = _bulk(app_client, [KALGUKSU, {**KALGUKSU, "address": "서울 성동구 비밀주소로 99"}])
    assert resp.status_code == 200
    assert "비밀주소" not in caplog.text and "37.5445" not in caplog.text and "성수 칼국수" not in caplog.text

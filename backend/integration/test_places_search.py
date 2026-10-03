"""GET /places/search (#180) — 검색 → 결과 그대로 핀 생성, 0건, 422, 429, 503. dev 모드(키 없음, 고정 샘플)로 돈다."""

import pytest

from auth.testing import session_cookie
from main import app  # noqa: F401
from places import api as places_api
from places.ratelimit import SlidingWindowLimiter
from places.service import PlaceService
from places.tests.test_name_search import NamedFake

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}


@pytest.fixture()
def client(app_client, two_users):
    from fastapi.testclient import TestClient

    c = TestClient(app_client.app, cookies=session_cookie("user_a"))   # with 없이 — lifespan은 app_client가 이미 연다
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(1000))


def _make_map(client):
    r = client.post("/maps", json={"title": "부산", "start_date": "2026-11-01", "end_date": "2026-11-03", "region": REGION})
    assert r.status_code == 201
    return r.json()["id"]


def test_search_result_outside_own_db_cannot_become_a_pin(client):
    """#195 — 검색 결과(카카오 쪽 장소)가 자체 DB에 짝이 없으면 핀이 되지 않는다. 이름·좌표를 그대로 꽂지 않는다."""
    map_id = _make_map(client)
    found = client.get("/places/search", params={"q": "해운대 밀면"})
    assert found.status_code == 200
    [hit] = found.json()
    assert set(hit) >= {"place_id", "place_name", "lat", "lng"} and hit["category"] == "음식점"
    assert hit["place_source"]["provider"] == "kakao"

    pin = client.post(f"/maps/{map_id}/pins", json={
        "category": hit["category"], "source": "search", "place_id": hit["place_id"],
        "place_name": hit["place_name"], "lat": hit["lat"], "lng": hit["lng"]})
    assert pin.status_code == 422 and pin.json()["code"] == "PLACE_NOT_SUPPORTED"
    assert client.get(f"/maps/{map_id}/pins").json() == []


def test_search_hint_for_an_own_db_place_becomes_a_pin_with_the_places_name(client, pin_body):
    map_id = _make_map(client)
    hint = pin_body("seongsu-kalguksu", place_name="성수 칼국수 본점", lat=37.5446, lng=127.0562)   # 카카오 쪽 표기·좌표
    pin = client.post(f"/maps/{map_id}/pins", json=hint)
    assert pin.status_code == 201, pin.text
    assert pin.json()["place_name"] == "성수 칼국수"                 # 자체 DB 이름
    assert (pin.json()["lat"], pin.json()["lng"]) == (37.5445, 127.0561)   # 자체 DB 좌표
    assert [p["place_name"] for p in client.get(f"/maps/{map_id}/pins").json()] == ["성수 칼국수"]


def test_results_carry_pinnable_computed_from_the_own_db(client, pin_body, fake_places, monkeypatch):
    """#238 — 검색 결과마다 자체 DB에 짝이 있는지 미리 알려 준다. 읽기만 한다(카카오 ID를 기록하지 않는다)."""
    [hit] = client.get("/places/search", params={"q": "해운대 밀면"}).json()
    assert hit["pinnable"] is False

    from places.schemas import PlaceSearchResult

    hint = pin_body("seongsu-kalguksu", place_name="성수 칼국수 본점")
    own = PlaceSearchResult(place_id=hint["place_id"], place_name=hint["place_name"], lat=hint["lat"], lng=hint["lng"], category="음식점")
    monkeypatch.setattr(places_api, "search_by_name", lambda q, near, limit: [own, own.model_copy(update={"place_id": "kakao:2", "place_name": "없는 가게"})])
    found = client.get("/places/search", params={"q": "성수"}).json()
    assert [r["pinnable"] for r in found] == [True, False]
    pid = fake_places.place_id("seongsu-kalguksu")
    assert places_api.get_places([pid])[pid].kakao_place_url is None


def test_pinnable_is_omitted_when_the_own_db_cannot_be_read(client, monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError

    def boom(hints, **kw):
        raise OperationalError("select", {"name": "해운대 밀면"}, Exception("db down"))

    monkeypatch.setattr(places_api, "pinnable_flags", boom)
    r = client.get("/places/search", params={"q": "해운대 밀면"})
    assert r.status_code == 200 and "pinnable" not in r.json()[0]
    assert "해운대" not in caplog.text and "OperationalError" in caplog.text   # 로그엔 예외 타입만(카카오 값 금지)


def test_partial_match_and_distance_order(client):
    r = client.get("/places/search", params={"q": "해운대", "lat": 35.1587, "lng": 129.1604})
    assert [p["place_name"] for p in r.json()] == ["해운대 바다 카페", "해운대 밀면"]


def test_query_is_stripped(client):
    assert len(client.get("/places/search", params={"q": "  광안리  "}).json()) == 2


def test_zero_results_is_empty_array(client):
    r = client.get("/places/search", params={"q": "존재하지않는가게"})
    assert r.status_code == 200 and r.json() == []


def test_limit_caps_results(client):
    assert len(client.get("/places/search", params={"q": "광안리", "limit": 1}).json()) == 1


@pytest.mark.parametrize("params", [
    {"q": ""}, {"q": "   "}, {"q": "가" * 51}, {},
    {"q": "a", "lat": 35.1}, {"q": "a", "lng": 129.1},
    {"q": "a", "lat": 91, "lng": 0}, {"q": "a", "lat": 0, "lng": 181},
    {"q": "a", "limit": 0}, {"q": "a", "limit": 16},
])
def test_invalid_params_are_422_validation_error(client, params):
    r = client.get("/places/search", params=params)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


def test_requires_login(app_client):
    from fastapi.testclient import TestClient

    anon = TestClient(app_client.app)
    assert anon.get("/places/search", params={"q": "a"}).status_code == 401


def test_does_not_require_map_membership(app_client, two_users):
    from fastapi.testclient import TestClient

    b = TestClient(app_client.app, cookies=session_cookie("user_b"))   # 어떤 지도의 구성원도 아니다
    assert b.get("/places/search", params={"q": "광안리"}).status_code == 200


def test_rate_limit_is_429_per_user(client, app_client, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(2))
    assert client.get("/places/search", params={"q": "광안리"}).status_code == 200
    assert client.get("/places/search", params={"q": "광안리"}).status_code == 200
    r = client.get("/places/search", params={"q": "광안리"})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))   # 다른 사용자는 별도로 센다
    assert b.get("/places/search", params={"q": "광안리"}).status_code == 200


def test_invalid_request_does_not_consume_the_limit(client, monkeypatch):
    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(1))
    assert client.get("/places/search", params={"q": ""}).status_code == 422
    assert client.get("/places/search", params={"q": "광안리"}).status_code == 200


def test_all_sources_failing_is_503(client, monkeypatch):
    failing = PlaceService([NamedFake("kakao", fail=True)])
    monkeypatch.setattr(places_api, "_is_dev", lambda: False)
    monkeypatch.setattr(places_api, "_service", lambda: failing)
    r = client.get("/places/search", params={"q": "아무거나"})
    assert r.status_code == 503 and r.json()["code"] == "PLACES_UNAVAILABLE"


def test_missing_key_is_503(client, monkeypatch):
    monkeypatch.setattr(places_api, "_is_dev", lambda: False)
    monkeypatch.setattr(places_api, "_service", lambda: PlaceService([NamedFake("kakao", configured=False)]))
    assert client.get("/places/search", params={"q": "a"}).status_code == 503

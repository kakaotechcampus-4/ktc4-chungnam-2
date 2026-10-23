"""광고 엔드포인트 2개 — 실제 앱, 실제 멤버십, 실제 places로 HTTP를 두드린다(docs/ads.md 11절 10·11·13·15번, 7절 오류).
요청 세션은 db_session(롤백)으로 바꿔 끼운다."""

import random
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ads import router as ads_router
from ads.tests.conftest import NOW, SEONGSU
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from pins.models import Pin

PARAMS = {"lat": SEONGSU[0], "lng": SEONGSU[1], "category": "카페"}


@pytest.fixture()
def client(world, db_session, monkeypatch):
    from main import app

    def _db():
        db_session.commit()   # 테스트가 flush만 해 둔 준비 데이터를 확정한다 — 요청이 오류로 롤백돼도 남는다(바깥 트랜잭션은 끝에 롤백)
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[ads_router.get_rng] = lambda: random.Random(7)
    monkeypatch.setattr(ads_router, "_now", lambda: NOW)
    made = []

    def as_user(name: str) -> TestClient:
        c = TestClient(app, cookies=session_cookie(world.uid(name)))
        made.append(c)
        return c

    yield as_user
    for c in made:
        c.close()
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(ads_router.get_rng, None)


# ---------------------------------------------------------------- 조회

def test_get_ads_returns_contract_shape_without_memo_or_counts_and_no_store(world, client):
    map_id = world.map()
    place = world.place("온도 커피", kakao_place_id="kakao:5", kakao_place_url="https://place.map.kakao.com/5")
    ad_id = world.ad(place, memo="광고주 A 비밀 메모")

    r = client("u1").get(f"/maps/{map_id}/ads", params=PARAMS)

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"                                   # 13
    body = r.json()
    assert body == {"ads": [{"ad_id": ad_id, "on_map": False, "place": {
        "place_id": place, "name": "온도 커피", "category": "카페", "address": "서울 성동구 성수동",
        "lat": pytest.approx(SEONGSU[0]), "lng": pytest.approx(SEONGSU[1]),
        "place_url": "https://place.map.kakao.com/5"}}]}
    text = r.text                                                                     # 11
    for leaked in ("memo", "광고주 A 비밀 메모", "served_count", "click_count", "starts_at", "ends_at", "active"):
        assert leaked not in text
    assert world.stats(ad_id) == {NOW.date(): (1, 0)}


def test_get_ads_without_category_and_with_no_ads(world, client):
    map_id = world.map()

    r = client("u2").get(f"/maps/{map_id}/ads", params={"lat": SEONGSU[0], "lng": SEONGSU[1]})

    assert r.status_code == 200 and r.json() == {"ads": []}
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("params", [
    {**PARAMS, "category": "숙소"},
    {**PARAMS, "category": "기타"},
    {**PARAMS, "category": "없는분류"},
    {**PARAMS, "lat": 90.1},
    {**PARAMS, "lng": -180.5},
    {"lng": SEONGSU[1]},
    {"lat": SEONGSU[0]},
])
def test_get_ads_rejects_bad_query_with_validation_error(world, client, params):
    map_id = world.map()

    r = client("u1").get(f"/maps/{map_id}/ads", params=params)

    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 10. 비구성원 404

def test_non_member_gets_404_for_both_endpoints_and_nothing_is_counted(world, client):
    map_id = world.map()
    ad_id = world.ad(world.place("카페"))
    world.outsider()
    stranger = client("stranger")

    got = stranger.get(f"/maps/{map_id}/ads", params=PARAMS)
    clicked = stranger.post(f"/ads/{ad_id}/clicks", json={"map_id": map_id})

    assert (got.status_code, got.json()["code"]) == (404, "NOT_FOUND")
    assert (clicked.status_code, clicked.json()["code"]) == (404, "NOT_FOUND")
    assert stranger.get("/maps/no-such-map/ads", params=PARAMS).status_code == 404
    assert world.stats(ad_id) == {}


def test_not_logged_in_is_401(world, client):
    from main import app

    map_id = world.map()
    with TestClient(app) as anon:
        assert anon.get(f"/maps/{map_id}/ads", params=PARAMS).status_code == 401
        assert anon.post(f"/ads/{world.ad(world.place('카페'))}/clicks", json={"map_id": map_id}).status_code == 401


# ---------------------------------------------------------------- 클릭

def test_click_is_204_and_counts_even_for_an_ended_ad(world, client):
    map_id = world.map()
    ad_id = world.ad(world.place("카페"))
    ended = world.ad(world.place("끝난 카페"), starts_at=NOW - timedelta(days=5), ends_at=NOW - timedelta(days=1))
    u2 = client("u2")

    assert u2.post(f"/ads/{ad_id}/clicks", json={"map_id": map_id}).status_code == 204
    assert u2.post(f"/ads/{ended}/clicks", json={"map_id": map_id}).status_code == 204

    assert world.stats(ad_id) == {NOW.date(): (0, 1)}
    assert world.stats(ended) == {NOW.date(): (0, 1)}


def test_click_on_missing_ad_is_404_for_members(world, client):
    map_id = world.map()

    r = client("u1").post("/ads/00000000-0000-0000-0000-000000000000/clicks", json={"map_id": map_id})

    assert (r.status_code, r.json()["code"]) == (404, "NOT_FOUND")


@pytest.mark.parametrize("body", [{}, {"map_id": ""}, {"map_id": "m", "user_id": "u"}])
def test_click_with_bad_body_is_validation_error(world, client, body):
    world.map()
    ad_id = world.ad(world.place("카페"))

    r = client("u1").post(f"/ads/{ad_id}/clicks", json=body)

    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_ERROR")


# ---------------------------------------------------------------- 15. 광고 장소를 지도에 올리기

def test_pin_from_an_ad_is_a_plain_direct_pin_like_any_other(world, client):
    """FE는 광고 응답의 place_id, name, lat, lng, category를 그대로 기존 핀 생성 API(source: search)로 보낸다."""
    map_id = world.map()
    ad_place = world.place("광고 카페", lat=SEONGSU[0], lng=SEONGSU[1])
    other = world.place("그냥 카페", lat=SEONGSU[0] + 0.01, lng=SEONGSU[1])
    world.ad(ad_place)
    u1 = client("u1")
    [ad] = u1.get(f"/maps/{map_id}/ads", params=PARAMS).json()["ads"]
    place = ad["place"]

    from_ad = u1.post(f"/maps/{map_id}/pins", json={
        "source": "search", "category": place["category"], "place_id": place["place_id"],
        "place_name": place["name"], "lat": place["lat"], "lng": place["lng"],
    })
    direct = u1.post(f"/maps/{map_id}/pins", json={
        "category": "카페", "place_id": f"own:{other}", "place_name": "그냥 카페", "lat": SEONGSU[0] + 0.01, "lng": SEONGSU[1],
    })

    assert from_ad.status_code == 201, from_ad.text
    assert direct.status_code == 201, direct.text
    pin, plain = from_ad.json(), direct.json()
    assert set(pin) == set(plain)
    assert (pin["kind"], pin.get("source")) == (plain["kind"], plain.get("source")) == ("일반", "db")
    rows = {str(r.id): r for r in world.db.execute(select(Pin).where(Pin.map_id == map_id)).scalars()}
    assert rows[pin["id"]].origin == rows[plain["id"]].origin == "direct"   # 응답 칸이 같고 DB에도 광고 흔적이 없다
    assert u1.get(f"/maps/{map_id}/ads", params=PARAMS).json()["ads"][0]["on_map"] is True

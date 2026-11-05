"""사용자가 정하는 추천 반경(#1416) — POST /maps/{mapId}/runs의 `radius_m`(정수 2000~5000, 없으면 3000)과 readiness 쿼리 `radius_m`.

서버는 사용자가 반경을 어떻게 고르는지 모르고 정수 하나만 받는다. 값은 run의 `default_radius_m`으로 저장돼 지역 원, 여행 지역 밖 판정
(`OUTSIDE_TRIP_REGION`), 넓히기(+1,000m, 상한 5,000m), 응답 칸이 모두 이어서 쓴다. 정책 값은 recommend/core.py 한 곳이다."""

import pytest
from sqlalchemy import select

from common.errors import AppError
from recommend import core, flows, schemas, service
from recommend.models import RecommendRun, Region
from recommend.tests.test_outside_trip_region_1385 import (  # noqa: F401 — 픽스처·보조 함수는 import로 쓴다
    CENTER, _count, _create, _Calls, real_places_map, _boundary, _square,
)
from recommend.tests.test_router import _auth, _seed_ready_map, app_client  # noqa: F401


# ---------------------------------------------------------------- 정책 값과 요청 모델

def test_policy_values_are_in_core_and_the_request_model_bounds_match_them():
    assert (core.MIN_RADIUS_M, core.DEFAULT_RADIUS_M, core.WIDEN_LIMIT_M) == (2000, 3000, 5000)   # 최대는 넓히기 상한과 같다
    field = schemas.RunCreateRequest.model_fields["radius_m"]
    by_type = {type(m).__name__: m for m in field.metadata}
    assert (by_type["Ge"].ge, by_type["Le"].le) == (core.MIN_RADIUS_M, core.WIDEN_LIMIT_M)   # 순환 import라 요청 모델에는 같은 값을 적었다


def test_request_radius_defaults_to_3000():
    assert core.request_radius_m(None) == 3000 and core.request_radius_m(2500) == 2500


# ---------------------------------------------------------------- 멱등 해시

def test_hash_ignores_an_explicit_default_and_changes_with_another_radius():
    omitted = core.idempotency_request_hash("m", "카페", False, (35.0, 129.0))
    assert core.idempotency_request_hash("m", "카페", False, (35.0, 129.0), 3000) == omitted   # 명시한 3000은 생략과 같다
    assert core.idempotency_request_hash("m", "카페", False, (35.0, 129.0), 2000) != omitted
    assert core.idempotency_request_hash("m", "카페", False, (35.0, 129.0), 2000) != core.idempotency_request_hash("m", "카페", False, (35.0, 129.0), 2500)
    # radius_m이 없는 옛 요청의 해시는 이전 값 그대로(옛 키 재시도 호환)
    assert core.idempotency_request_hash("m", "카페") == core.idempotency_request_hash("m", "카페", False, None, None)


# ---------------------------------------------------------------- 요청 본문 검증 (HTTP)

@pytest.mark.parametrize("radius_m", [2000, 2500, 5000])
def test_a_radius_in_range_is_saved_as_the_runs_default_radius_and_continues_into_next(app_client, db_session, monkeypatch, radius_m):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)

    created = app_client.post("/maps/map_1/runs", json={"category": "음식점", "radius_m": radius_m}, cookies=_auth("user_1"))

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["default_radius_m"] == radius_m
    assert body["next_default_radius_m"] == (core.next_default_radius_m(radius_m))   # 2000 → 3000, 2500 → 3500, 5000 → null
    assert (radius_m == 5000) == (body["next_default_radius_m"] is None)
    summary = app_client.get("/maps/map_1/runs", cookies=_auth("user_1")).json()[0]
    assert (summary["default_radius_m"], summary["next_default_radius_m"]) == (body["default_radius_m"], body["next_default_radius_m"])
    run = db_session.execute(select(RecommendRun)).scalars().one()
    assert (run.default_radius_m, run.default_radius_walk_min) == (radius_m, round(radius_m / 80))
    region = db_session.execute(select(Region)).scalars().one()
    assert region.radius_m == radius_m   # 후보를 찾는 원의 반경도 같다


@pytest.mark.parametrize("radius_m", [1999, 5001, 0, -3000, 2500.5, 3000.0, "3000", "abc", True, None, [], {}])
def test_a_radius_out_of_range_or_not_an_integer_is_422_and_makes_nothing(app_client, db_session, monkeypatch, radius_m):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)

    resp = app_client.post("/maps/map_1/runs", json={"category": "음식점", "radius_m": radius_m}, cookies=_auth("user_1"))

    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert _count(db_session, RecommendRun) == 0


def test_without_a_radius_the_run_is_exactly_as_before_3000(app_client, db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)

    omitted = app_client.post("/maps/map_1/runs", json={"category": "음식점"}, cookies=_auth("user_1")).json()
    explicit = app_client.post("/maps/map_1/runs", json={"category": "음식점", "radius_m": 3000}, cookies=_auth("user_1")).json()

    assert (omitted["default_radius_m"], omitted["next_default_radius_m"]) == (3000, 4000)
    assert (explicit["default_radius_m"], explicit["next_default_radius_m"]) == (3000, 4000)


# ---------------------------------------------------------------- 반경 넓히기가 고른 반경에서 이어진다

def test_widen_continues_from_the_chosen_radius_and_stops_at_the_limit(app_client, db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)
    run_id = app_client.post("/maps/map_1/runs", json={"category": "음식점", "radius_m": 2000}, cookies=_auth("user_1")).json()["id"]

    seen = []
    for _ in range(3):
        resp = app_client.post(f"/runs/{run_id}/widen", cookies=_auth("user_1"))
        assert resp.status_code == 202, resp.text
        seen.append((resp.json()["default_radius_m"], resp.json()["next_default_radius_m"]))
    assert seen == [(3000, 4000), (4000, 5000), (5000, None)]
    assert app_client.post(f"/runs/{run_id}/widen", cookies=_auth("user_1")).json()["code"] == "WIDEN_LIMIT"


def test_a_run_started_at_the_limit_cannot_widen(app_client, db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)
    run_id = app_client.post("/maps/map_1/runs", json={"category": "음식점", "radius_m": 5000}, cookies=_auth("user_1")).json()["id"]
    resp = app_client.post(f"/runs/{run_id}/widen", cookies=_auth("user_1"))
    assert resp.status_code == 409 and resp.json()["code"] == "WIDEN_LIMIT"


# ---------------------------------------------------------------- 여행 지역 밖 판정이 고른 반경으로

def test_the_trip_region_check_uses_the_chosen_radius(real_places_map, monkeypatch):
    """서울 서쪽 경계에서 약 4km 밖(경기)에서 반경 2000이면 원 전체가 서울 밖(422), 5000이면 원이 서울에 걸쳐 통과한다."""
    west_of_seoul = (37.5, 126.9545)   # 위도 37.5에서 경도 0.0455° ≈ 4.0km
    with pytest.raises(AppError) as outside:
        _create(real_places_map, center=west_of_seoul, radius_m=2000)
    assert outside.value.code == "OUTSIDE_TRIP_REGION"

    straddling = _create(real_places_map, center=west_of_seoul, radius_m=5000)
    assert straddling.default_radius_m == 5000 and straddling.status == "collecting_evidence"


def test_the_check_receives_the_chosen_radius(real_places_map, monkeypatch):
    check = _Calls(False)
    monkeypatch.setattr(flows, "_circle_outside_region", check)
    _create(real_places_map, center=(37.5, 127.5), radius_m=2500)
    _create(real_places_map, center=(37.5, 127.5))
    assert [c["radius_m"] for c in check.calls] == [2500, 3000]


# ---------------------------------------------------------------- readiness 쿼리

def test_readiness_gives_the_range_and_accepts_a_radius_query(app_client, db_session):
    _seed_ready_map(db_session)
    base = app_client.get("/maps/map_1/recommend/readiness", cookies=_auth()).json()["음식점"]
    assert (base["radius_m"], base["radius_min_m"], base["radius_max_m"]) == (3000, 2000, 5000)

    for radius in ("2000", "3500", "5000"):
        resp = app_client.get("/maps/map_1/recommend/readiness", params={"radius_m": radius, "center_lat": 37.5, "center_lng": 127.0}, cookies=_auth())
        assert resp.status_code == 200, resp.text
        assert resp.json()["음식점"]["radius_m"] == 3000   # 기본값은 그대로 — 고른 값이 아니다
    without_center = app_client.get("/maps/map_1/recommend/readiness", params={"radius_m": "2500"}, cookies=_auth())
    assert without_center.status_code == 200   # center 없이도 받는다(핀 기반 경로의 원 반경)


@pytest.mark.parametrize("radius", ["1999", "5001", "3000.0", "abc", "-1", "", "2500.5", "０３０００", "3000 ", "3000\n", "٣٠٠٠"])
def test_readiness_radius_query_must_be_digits_in_range(app_client, db_session, radius):
    _seed_ready_map(db_session)
    resp = app_client.get("/maps/map_1/recommend/readiness", params={"radius_m": radius}, cookies=_auth())
    assert resp.status_code == 422, (radius, resp.text)
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_readiness_count_circle_uses_the_chosen_radius_but_the_pool_is_the_limit(db_session):
    """원 반경은 고른 값이고 후보 풀은 언제나 상한(5,000m)이다 — 넓혀서 닿을 수 있는 곳까지 센다(#798, #792)."""
    from recommend.tests.test_external_search import CATEGORY, _Places
    from recommend.tests.test_flows import _make_members, _make_pin, _react

    _make_members(db_session, user_ids=["user_1"])
    _react(db_session, _make_pin(db_session, category=CATEGORY, lat=37.5, lng=127.0), user_id="user_1")
    for radius in (2000, 5000):
        places = _Places(curated=3)
        flows.get_readiness(db_session, map_id="map_1", place_search=places, center=(37.5, 127.0), radius_m=radius)
        assert all(circle.radius_m == core.WIDEN_LIMIT_M for circle in places.curated_circles[0])
        places = _Places(curated=3)
        flows.get_readiness(db_session, map_id="map_1", place_search=places, radius_m=radius)   # center 없는 핀 기반 경로
        assert all(circle.radius_m == core.WIDEN_LIMIT_M for circle in places.curated_circles[0])

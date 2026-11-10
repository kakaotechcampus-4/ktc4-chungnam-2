"""사용자가 정하는 추천 반경(#1416) — POST /maps/{mapId}/runs의 `radius_m`(정수 2000~5000, 없으면 3000)과 readiness 쿼리 `radius_m`.

서버는 사용자가 반경을 어떻게 고르는지 모르고 정수 하나만 받는다. 값은 run의 `default_radius_m`으로 저장돼 지역 원, 여행 지역 밖 판정
(`OUTSIDE_TRIP_REGION`), 넓히기(+1,000m, 상한 5,000m), 응답 칸이 모두 이어서 쓴다. 정책 값은 recommend/core.py 한 곳이다."""

import hashlib

import pytest
from sqlalchemy import select

from common.errors import AppError
from recommend import core, flows, schemas, service
from recommend.models import RecommendRun, Region
from recommend.tests.test_outside_trip_region_1385 import (  # noqa: F401 — 픽스처·보조 함수는 import로 쓴다
    CENTER, _count, _create, _Calls, real_places_map, _boundary, _square,
)
from recommend.ports import PlaceStub
from recommend.tests.test_flows import PLANNER, _CirclePlaceSearch, _RecordingPlaceFacts, _make_members, _make_pin, _react
from recommend.tests.test_router import RUN_CENTER, _auth, _seed_ready_map, app_client  # noqa: F401


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
    # radius_m이 없는 요청의 해시는 이전 값 그대로 — 고정값으로 비교한다(radius_m이 생기기 전에 만든 키의 재시도가 같은 run을 받는다)
    assert omitted == hashlib.sha256("m카페035129".encode()).hexdigest()


# ---------------------------------------------------------------- 요청 본문 검증 (HTTP)

@pytest.mark.parametrize("radius_m", [2000, 2500, 5000])
def test_a_radius_in_range_is_saved_as_the_runs_default_radius_and_continues_into_next(app_client, db_session, monkeypatch, radius_m):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)

    created = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER, "radius_m": radius_m}, cookies=_auth("user_1"))

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["default_radius_m"] == radius_m
    assert body["next_default_radius_m"] == {2000: 3000, 2500: 3500, 5000: None}[radius_m]   # 리터럴로 적는다(구현 함수를 다시 부르지 않는다)
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

    resp = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER, "radius_m": radius_m}, cookies=_auth("user_1"))

    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert _count(db_session, RecommendRun) == 0


def test_without_a_radius_the_run_is_exactly_as_before_3000(app_client, db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)

    omitted = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER}, cookies=_auth("user_1")).json()
    explicit = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER, "radius_m": 3000}, cookies=_auth("user_1")).json()

    assert (omitted["default_radius_m"], omitted["next_default_radius_m"]) == (3000, 4000)
    assert (explicit["default_radius_m"], explicit["next_default_radius_m"]) == (3000, 4000)


# ---------------------------------------------------------------- 반경 넓히기가 고른 반경에서 이어진다

def test_widen_continues_from_the_chosen_radius_and_stops_at_the_limit(app_client, db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _seed_ready_map(db_session)
    run_id = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER, "radius_m": 2000}, cookies=_auth("user_1")).json()["id"]

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
    run_id = app_client.post("/maps/map_1/runs", json={"category": "음식점", "center": RUN_CENTER, "radius_m": 5000}, cookies=_auth("user_1")).json()["id"]
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


def test_a_5000_digit_query_is_422_not_500(app_client, db_session):
    """파이썬 정수 문자열 변환 제한(4300자리)을 넘는 숫자 문자열도 500이 아니라 422다."""
    _seed_ready_map(db_session)
    for radius in ("9" * 5000, "9" * 8, "0" * 7 + "1"):
        resp = app_client.get("/maps/map_1/recommend/readiness", params={"radius_m": radius}, cookies=_auth())
        assert resp.status_code == 422, (radius[:12], resp.status_code)
        assert resp.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 실제 장소 배치 — 고른 반경 안·밖·5,000m 밖 (리터럴 값으로 단언)

# 중심 (35.0, 129.0)에서 북쪽으로 약 1,501m·2,502m·3,503m·4,504m·6,503m 떨어진 다섯 곳(위도 1° = 111,195m).
P1500 = PlaceStub(place_id="p1500", lat=35.0135, lng=129.0)
P2500 = PlaceStub(place_id="p2500", lat=35.0225, lng=129.0)
P3500 = PlaceStub(place_id="p3500", lat=35.0315, lng=129.0)
P4500 = PlaceStub(place_id="p4500", lat=35.0405, lng=129.0)
P6500 = PlaceStub(place_id="p6500", lat=35.0585, lng=129.0)   # 상한(5,000m) 밖 — 어떤 반경에서도 풀에 없다
MAP_CENTER = (35.0, 129.0)


class _MeterPlaces(_CirclePlaceSearch):
    """받은 원 안의 장소만 주고 세는 것도 같은 기준이다(실구현 ST_DWithin처럼). 받은 원 반경을 남긴다."""

    def count_curated(self, *, category, circles):
        return len(self.search_nearby(category=category, circles=circles))


def _ready_pin(db):
    _make_members(db, user_ids=["user_1"])
    _react(db, _make_pin(db, category="음식점", lat=35.0, lng=129.0), user_id="user_1", type="like")
    db.commit()


def test_readiness_counts_only_inside_the_chosen_radius_and_without_a_query_keeps_the_5000_pool(db_session):
    """고른 반경이 있으면 curated_nearby는 그 반경 원 안의 수다(화면의 숫자가 고른 반경을 따른다). 쿼리가 없으면 지금 동작(상한 5,000m 풀)."""
    _ready_pin(db_session)
    places = _MeterPlaces([P1500, P2500, P3500, P4500, P6500])

    def counted(**kwargs):
        return flows.get_readiness(db_session, map_id="map_1", place_search=places, **kwargs)["음식점"]["curated_nearby"]

    assert [counted(center=MAP_CENTER, radius_m=r) for r in (2000, 3000, 4000, 5000)] == [1, 2, 3, 4]   # 단조 증가, 6,503m는 어디에도 안 든다
    assert counted(center=MAP_CENTER) == 4                                                              # radius_m 없음: 5,000m 풀(옛 클라이언트·agent 호환)
    assert [counted(radius_m=r) for r in (2000, 3000, 5000)] == [1, 2, 4]                                # center 없는 핀 기반 경로도 같다(핀이 (35.0, 129.0))
    assert counted() == 4


def test_readiness_zero_inside_the_chosen_radius_gives_the_search_link_even_though_the_pool_has_places(db_session):
    """고른 반경 안이 0곳이면 external_search를 함께 준다 — 수와 같은 기준이다."""
    _ready_pin(db_session)
    places = _MeterPlaces([P2500, P4500])   # 2,502m·4,504m — 2,000m 안에는 없다

    narrow = flows.get_readiness(db_session, map_id="map_1", place_search=places, center=MAP_CENTER, radius_m=2000)["음식점"]
    assert narrow["curated_nearby"] == 0 and "external_search" in narrow
    wide = flows.get_readiness(db_session, map_id="map_1", place_search=places, center=MAP_CENTER, radius_m=5000)["음식점"]
    assert wide["curated_nearby"] == 2 and "external_search" not in wide
    default = flows.get_readiness(db_session, map_id="map_1", place_search=places, center=MAP_CENTER)["음식점"]
    assert default["curated_nearby"] == 2   # 쿼리 없음 = 5,000m 풀


def _removed(run, label="반경 밖 제거") -> int:
    return {e["label"]: e["removed_count"] for e in run.last_funnel}[label]


@pytest.fixture
def started_at_2000(db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _ready_pin(db_session)
    places = _MeterPlaces([P1500, P2500, P3500, P4500, P6500])
    facts = _RecordingPlaceFacts()
    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=PLANNER,
                           center=MAP_CENTER, radius_m=2000)
    return db_session, run, places, facts


def _candidates(db, run) -> set[str]:
    return {c.place_id for c in service.list_candidates(db, str(run.id))}


def test_execute_widen_and_retry_follow_the_chosen_radius(started_at_2000):
    """2000으로 시작한 run: 실행은 2,000m 안(1곳)만, 반경 밖 제거는 풀(5,000m 안 4곳) 중 3곳. 넓히면 3000(2곳, 제거 2) → 4000(3곳, 제거 1).
    다시 추천은 저장된 반경(그때의 반경)으로 찾고, 상한 풀은 5,000m 그대로다. 6,503m는 풀에도 없다."""
    db, run, places, facts = started_at_2000

    flows.execute_run(db, run_id=str(run.id), place_search=places, place_facts=facts)
    assert places.radii[-2:] == [[5000], [2000]]                 # 풀 5,000m, 지금 반경 2,000m
    assert _candidates(db, run) == {"p1500"} and _removed(run) == 3
    assert "p6500" not in facts.read and "p4500" not in facts.read   # 반경 밖 장소의 라벨은 읽지 않는다

    flows.widen_run(db, run_id=str(run.id), place_search=places, place_facts=facts)
    assert places.radii[-2:] == [[5000], [3000]]
    assert (run.default_radius_m, _candidates(db, run), _removed(run)) == (3000, {"p1500", "p2500"}, 2)

    flows.widen_run(db, run_id=str(run.id), place_search=places, place_facts=facts)
    assert places.radii[-2:] == [[5000], [4000]]
    assert (run.default_radius_m, _candidates(db, run), _removed(run)) == (4000, {"p1500", "p2500", "p3500"}, 1)

    flows.retry_run(db, run_id=str(run.id), place_search=places, place_facts=facts)   # 지금 뜬 후보를 제외하고 저장된 4,000m로 다시 찾는다
    assert places.radii[-2:] == [[5000], [4000]]
    assert _candidates(db, run) == set() and _removed(run) == 1       # 4,000m 안 세 곳은 모두 제외돼 비고, 4,504m는 반경 밖


def test_a_run_started_at_5000_searches_the_whole_pool_as_its_radius(db_session, monkeypatch):
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "sido")
    _ready_pin(db_session)
    places, facts = _MeterPlaces([P1500, P2500, P3500, P4500, P6500]), _RecordingPlaceFacts()
    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=PLANNER,
                           center=MAP_CENTER, radius_m=5000)

    flows.execute_run(db_session, run_id=str(run.id), place_search=places, place_facts=facts)

    assert places.radii[-2:] == [[5000], [5000]]    # 풀과 반경이 같다
    assert _removed(run) == 0 and len(_candidates(db_session, run)) == 3   # 4곳이 통과하고 상위 3곳이 남는다
    assert "p6500" not in facts.read


def test_the_simulation_factor_limit_follows_the_chosen_radius(started_at_2000):
    """시뮬레이션이 허용하는 배율 상한은 5,000m / 고른 반경이다 — 2000이면 2.5배, 그보다 크면 ValueError."""
    db, run, places, facts = started_at_2000
    flows.execute_run(db, run_id=str(run.id), place_search=places, place_facts=facts)

    ok = flows.simulate_filter(db, run_id=str(run.id), radius_factor=2.5, disable_line_ids=[], place_search=places, place_facts=facts)
    assert (ok["before"]["passed_count"], ok["after"]["passed_count"]) == (1, 4)
    with pytest.raises(ValueError):
        flows.simulate_filter(db, run_id=str(run.id), radius_factor=2.51, disable_line_ids=[], place_search=places, place_facts=facts)

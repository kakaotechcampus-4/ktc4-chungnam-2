"""POST /maps/{mapId}/runs — 요청 center 기준 반경 3km 원 전체가 지도의 여행 지역(시·도) 밖이면 422 OUTSIDE_TRIP_REGION(#1385).

경계 판정은 places(시·도 경계 데이터)가 하고, recommend는 `flows._circle_outside_region` 한 곳으로만 부른다. 이 시험은 그 자리를
가짜로 바꿔 끼워 recommend 쪽 규칙을 본다: 원 전체가 밖일 때만 막고(걸치기만 하면 통과), 지도에 여행 지역이 없거나 경계를 모르면
(None) 막지 않으며, 막힌 요청은 크레딧·run·모델 호출을 하나도 쓰지 않는다. 검증 오류(center 없음, 시·도를 정할 수 없는 곳)가 먼저다."""

import pytest
from sqlalchemy import func, select

from common.errors import AppError
from credits.models import CreditLedger
from recommend import core, flows
from recommend.models import RecommendRun
from recommend.tests.test_flows import PLANNER, _make_members, _make_pin, _react

CENTER = (35.1, 129.0)
TRIP_CENTER = (37.5665, 126.9780)   # 지도 여행 지역 중심(서울)


class _Calls:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def __call__(self, db, *, center, radius_m, sido):
        self.calls.append({"center": center, "radius_m": radius_m, "sido": sido})
        return self.answer


@pytest.fixture
def ready_map(db_session, monkeypatch):
    """의견 핀이 있어 추천이 준비된 지도. 여행 지역은 서울(지도 중심·이름), 시·도 판정은 모두 「서울」이다."""
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "서울")
    monkeypatch.setattr(flows.maps_api, "get_map_region_center", lambda db, map_id: TRIP_CENTER)
    monkeypatch.setattr(flows.maps_api, "get_map_region_label", lambda db, map_id: "서울")
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")
    db_session.commit()
    return db_session


def _create(db, **kwargs):
    return flows.create_run(db, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=PLANNER,
                            center=kwargs.pop("center", CENTER), **kwargs)


def _count(db, model, *conditions) -> int:
    return db.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one()


def test_a_circle_entirely_outside_the_trip_region_is_422_and_uses_nothing(ready_map, monkeypatch):
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)
    planned = []
    monkeypatch.setattr(PLANNER, "plan_evidence", lambda raw: planned.append(raw) or [])

    with pytest.raises(AppError) as exc:
        _create(ready_map)

    assert exc.value.code == "OUTSIDE_TRIP_REGION"
    assert exc.value.detail == {"region_label": "서울"}
    assert core.DEFAULT_RADIUS_M == 3000
    assert check.calls == [{"center": CENTER, "radius_m": 3000, "sido": "서울"}]
    assert planned == []                                        # 모델(②)을 부르지 않는다
    assert _count(ready_map, RecommendRun) == 0                 # run이 없다
    assert _count(ready_map, CreditLedger, CreditLedger.user_id == "user_1") == 0   # 크레딧 원장도 그대로(계정도 만들지 않는다)


@pytest.mark.parametrize("answer", [False, None], ids=["걸치기만 함(밖이 아니다)", "경계 데이터 없음(모름)"])
def test_straddling_or_unknown_boundary_is_not_blocked(ready_map, monkeypatch, answer):
    check = _Calls(answer)
    monkeypatch.setattr(flows, "_circle_outside_region", check)

    run = _create(ready_map)

    assert run.status == "collecting_evidence" and len(check.calls) == 1
    assert (run.origin_lat, run.origin_lng) == CENTER


def test_a_map_without_a_trip_region_is_never_blocked(ready_map, monkeypatch):
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)
    monkeypatch.setattr(flows.maps_api, "get_map_region_center", lambda db, map_id: None)

    run = _create(ready_map)

    assert run.status == "collecting_evidence"
    assert check.calls == []   # 여행 지역이 없으면 경계를 묻지도 않는다


def test_an_unknown_trip_sido_is_not_blocked(ready_map, monkeypatch):
    """여행 지역 중심의 시·도를 모르면(None) 막지 않는다 — 모름을 실격으로 읽지 않는다(후보를 시·도로 거르는 곳과 같다)."""
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)
    monkeypatch.setattr(flows.places_api, "sido_at", lambda lat, lng, **kw: None if (lat, lng) == TRIP_CENTER else "부산")

    assert _create(ready_map).status == "collecting_evidence"
    assert check.calls == []


def test_the_label_falls_back_to_the_sido_when_the_map_has_no_label(ready_map, monkeypatch):
    monkeypatch.setattr(flows, "_circle_outside_region", _Calls(True))
    monkeypatch.setattr(flows.maps_api, "get_map_region_label", lambda db, map_id: None)

    with pytest.raises(AppError) as exc:
        _create(ready_map)
    assert exc.value.detail == {"region_label": "서울"}


def test_validation_errors_come_before_the_region_check(ready_map, monkeypatch):
    """시·도를 정할 수 없는 center는 VALIDATION_ERROR가 먼저다 — 경계 판정은 부르지도 않는다. (center가 없는 요청은 요청 모델이 먼저 막는다.)"""
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)

    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: None)
    with pytest.raises(AppError) as unknown_sido:
        _create(ready_map)
    assert unknown_sido.value.code == "VALIDATION_ERROR"
    assert check.calls == []


def test_not_ready_comes_before_the_region_check(db_session, monkeypatch):
    """준비 미달(409)이 지역 판정(422)보다 먼저다 — 의견 핀이 없는 지도는 지역을 묻지도 않는다."""
    monkeypatch.setattr(flows.places_api, "sido_at", lambda *a, **kw: "서울")
    monkeypatch.setattr(flows.maps_api, "get_map_region_center", lambda db, map_id: TRIP_CENTER)
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)
    _make_members(db_session, user_ids=["user_1"])

    with pytest.raises(AppError) as exc:
        _create(db_session)
    assert exc.value.code == "NOT_READY" and check.calls == []


# ---------------------------------------------------------------- 실제 places 함수(합성 시·도 경계) — 가짜를 끼우지 않는다

def _square(lat0, lng0, lat1, lng1):
    return [[lat0, lng0], [lat0, lng1], [lat1, lng1], [lat1, lng0]]


def _boundary(db, code, name, polygons):
    from places import boundaries, repository
    repository.upsert_boundaries(db, [{"code": code, "name": name, "wkt": boundaries.to_wkt(polygons), "sha256": "x" * 64}])


def _place(db, lat, lng, address, source_id):
    from places.models import Place
    db.add(Place(source="permit", source_id=source_id, name="가게", category="음식점", address=address,
                 geom=f"SRID=4326;POINT({lng} {lat})"))
    db.flush()


@pytest.fixture
def real_places_map(db_session, monkeypatch):
    """지도 여행 지역은 서울(37~38°N, 127~128°E 사각형)이고 경기는 그 서쪽 이웃이다. places는 진짜이고, 지도 여행 지역 중심·이름만 바꿔 끼운다."""
    _boundary(db_session, "11", "서울", [[_square(37, 127, 38, 128)]])
    _boundary(db_session, "31", "경기", [[_square(37, 126, 38, 127)]])
    monkeypatch.setattr(flows.maps_api, "get_map_region_center", lambda db, map_id: (37.5, 127.5))
    monkeypatch.setattr(flows.maps_api, "get_map_region_label", lambda db, map_id: "서울")
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")
    db_session.commit()
    return db_session


def _nothing_used(db, planned) -> None:
    assert planned == []                                                          # 모델(②) 0회
    assert _count(db, RecommendRun) == 0                                          # run 0건
    assert _count(db, CreditLedger, CreditLedger.user_id == "user_1") == 0        # 크레딧 원장 불변(계정도 없다)


def test_real_places_downtown_seoul_and_a_circle_straddling_the_border_pass(real_places_map):
    inside = _create(real_places_map, center=(37.5, 127.5))                       # 원이 서울 안
    assert inside.status == "collecting_evidence"
    straddling = _create(real_places_map, center=(37.5, 126.998))                 # 서쪽 경계에서 약 180m 밖 — 3km 원이 서울에 걸친다
    assert straddling.status == "collecting_evidence"


def test_real_places_a_circle_entirely_outside_seoul_is_422_and_uses_nothing(real_places_map, monkeypatch):
    planned = []
    monkeypatch.setattr(PLANNER, "plan_evidence", lambda raw: planned.append(raw) or [])

    with pytest.raises(AppError) as exc:
        _create(real_places_map, center=(37.5, 126.5))                            # 경기 한가운데, 서울 경계에서 약 44km

    assert exc.value.code == "OUTSIDE_TRIP_REGION" and exc.value.detail == {"region_label": "서울"}
    _nothing_used(real_places_map, planned)


def test_real_places_a_coastal_point_off_the_boundary_is_judged_by_the_nearest_place_sido(real_places_map, monkeypatch):
    """경계에 안 드는 해안 점(간소화 경계가 빠뜨린 곳)은 places가 가까운 장소의 시·도로 정한다 — 부산 장소 근처라 서울 밖 → 422."""
    _boundary(real_places_map, "21", "부산", [[_square(35.0, 129.0, 35.1, 129.2)]])
    _place(real_places_map, 35.12, 129.1, "부산광역시 해운대구 1", "coast1")
    planned = []
    monkeypatch.setattr(PLANNER, "plan_evidence", lambda raw: planned.append(raw) or [])

    with pytest.raises(AppError) as exc:
        _create(real_places_map, center=(35.115, 129.1))                          # 부산 경계 밖(바다)이지만 부산 장소가 가깝다

    assert exc.value.code == "OUTSIDE_TRIP_REGION"
    _nothing_used(real_places_map, planned)


def test_real_places_a_point_whose_sido_cannot_be_decided_is_a_validation_error_first(real_places_map, monkeypatch):
    """먼 바다 위(경계에도 안 들고 가까운 장소도 없다)는 시·도를 정할 수 없어 VALIDATION_ERROR가 먼저다 — OUTSIDE_TRIP_REGION이 아니다."""
    planned = []
    monkeypatch.setattr(PLANNER, "plan_evidence", lambda raw: planned.append(raw) or [])

    with pytest.raises(AppError) as exc:
        _create(real_places_map, center=(35.0, 131.0))

    assert exc.value.code == "VALIDATION_ERROR"
    _nothing_used(real_places_map, planned)


def test_real_places_without_boundary_data_it_never_blocks(db_session, monkeypatch):
    """경계 표가 비어 있으면(적재 전 환경) places가 None을 돌려 막지 않는다. 시·도는 가까운 장소 주소로 정해진다(되돌아가기)."""
    from places.models import SidoBoundary
    assert _count(db_session, SidoBoundary) == 0
    _place(db_session, 37.5, 127.5, "서울특별시 강남구 1", "seoul1")
    _place(db_session, 35.1, 129.0, "부산광역시 해운대구 1", "busan1")
    monkeypatch.setattr(flows.maps_api, "get_map_region_center", lambda db, map_id: (37.5, 127.5))
    monkeypatch.setattr(flows.maps_api, "get_map_region_label", lambda db, map_id: "서울")
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")
    db_session.commit()

    run = _create(db_session, center=(35.1, 129.0))                               # 부산 — 경계 데이터가 없으니 막지 않는다

    assert run.status == "collecting_evidence"


def test_the_real_check_calls_places_with_the_policy_radius(db_session, monkeypatch):
    seen = []
    monkeypatch.setattr(flows.places_api, "circle_outside_region",
                        lambda lat, lng, radius_m, sido, *, db=None: seen.append((lat, lng, radius_m, sido)) or True)
    assert flows._circle_outside_region(db_session, center=CENTER, radius_m=core.DEFAULT_RADIUS_M, sido="서울") is True
    assert seen == [(35.1, 129.0, 3000, "서울")]

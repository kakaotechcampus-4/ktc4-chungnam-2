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


@pytest.mark.no_center_shim
def test_validation_errors_come_before_the_region_check(ready_map, monkeypatch):
    """center 없음, 시·도를 정할 수 없는 center는 VALIDATION_ERROR가 먼저다 — 경계 판정은 부르지도 않는다."""
    check = _Calls(True)
    monkeypatch.setattr(flows, "_circle_outside_region", check)

    with pytest.raises(AppError) as no_center:
        _create(ready_map, center=None)
    assert no_center.value.code == "VALIDATION_ERROR"

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


def test_the_real_check_is_not_wired_until_places_has_it_so_it_never_blocks():
    """places.api.circle_outside_region(PR #1400)이 들어오기 전의 기본 본문 — 모름(None)이라 아무것도 막지 않는다.
    #1400 병합 뒤 실연결 커밋이 이 시험을 places의 함수를 부르는 시험으로 바꾼다."""
    assert flows._circle_outside_region(None, center=CENTER, radius_m=3000, sido="서울") is None

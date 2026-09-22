import math

import pytest

from common.geo import EARTH_RADIUS_M, Point, approx_walk_minutes, haversine_distance_m, nearest_neighbor_order


def test_haversine_distance_same_point_is_zero():
    assert haversine_distance_m(37.5, 127.0, 37.5, 127.0) == 0


def test_haversine_distance_near_antipodal_points_does_not_raise():
    # 거의 정확히 정반대인 두 좌표 — 실제로 재현 확인함: 부동소수점 오차로 중간값 a가
    # 1.0000000000000004처럼 1.0을 미세하게 넘어서면 asin(sqrt(a))가 math domain error를
    # 낸다(Antigravity 검수 지적). 클램핑 없이는 이 테스트가 ValueError로 죽는다.
    lat1, lng1 = 59.46980154989913, -53.99965407068102
    lat2, lng2 = -59.469801550745494, 126.00034592931898
    distance_m = haversine_distance_m(lat1, lng1, lat2, lng2)
    assert distance_m == pytest.approx(math.pi * EARTH_RADIUS_M, rel=1e-6)


def test_haversine_distance_known_pair_is_roughly_correct():
    # 서울시청(37.5665, 126.9780) ~ 부산시청(35.1796, 129.0756) 실제 직선거리는 약 325km.
    seoul = (37.5665, 126.9780)
    busan = (35.1796, 129.0756)
    distance_km = haversine_distance_m(*seoul, *busan) / 1000
    assert 320 < distance_km < 330


def test_approx_walk_minutes_uses_documented_speed_and_floors_at_one():
    assert approx_walk_minutes(0) == 1
    assert approx_walk_minutes(80) == 1
    assert approx_walk_minutes(800) == 10


def test_nearest_neighbor_order_empty_input():
    assert nearest_neighbor_order([]) == []


def test_nearest_neighbor_order_visits_closer_point_first():
    # a(0,0) 출발 시 b(0,0.001)가 c(0,0.01)보다 훨씬 가까우니 b가 먼저 나와야 한다.
    a = Point("a", 0.0, 0.0)
    b = Point("b", 0.0, 0.001)
    c = Point("c", 0.0, 0.01)
    assert nearest_neighbor_order([a, c, b]) == ["a", "b", "c"]


def test_nearest_neighbor_order_respects_start_id():
    a = Point("a", 0.0, 0.0)
    b = Point("b", 0.0, 0.001)
    c = Point("c", 0.0, 0.01)
    result = nearest_neighbor_order([a, b, c], start_id="c")
    assert result[0] == "c"
    assert set(result) == {"a", "b", "c"}


def test_nearest_neighbor_order_raises_on_unknown_start_id():
    # Antigravity 검수 지적 — 이전엔 next()가 기본값 없이 StopIteration을 냈다(조용히 죽는
    # 대신 명확한 에러로 실패해야 한다, docs/code-quality.md).
    a = Point("a", 0.0, 0.0)
    b = Point("b", 0.0, 0.001)
    with pytest.raises(ValueError):
        nearest_neighbor_order([a, b], start_id="does-not-exist")


def test_nearest_neighbor_order_visits_every_point_exactly_once():
    points = [Point(f"p{i}", math.sin(i), math.cos(i)) for i in range(12)]
    result = nearest_neighbor_order(points)
    assert sorted(result) == sorted(p.id for p in points)

import math

from common.geo import Point, approx_walk_minutes, haversine_distance_m, nearest_neighbor_order


def test_haversine_distance_same_point_is_zero():
    assert haversine_distance_m(37.5, 127.0, 37.5, 127.0) == 0


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


def test_nearest_neighbor_order_visits_every_point_exactly_once():
    points = [Point(f"p{i}", math.sin(i), math.cos(i)) for i in range(12)]
    result = nearest_neighbor_order(points)
    assert sorted(result) == sorted(p.id for p in points)

"""순수 함수 테스트 — DB 없이 돌아간다(docs/code-quality.md). shortlist/CLAUDE.md 완료 정의의
"8km 이상 떨어진 두 클러스터" 케이스를 여기서 먼저 순수 계산으로 고정하고, API 레벨
테스트(test_route_api.py)에서 같은 케이스를 실제 엔드포인트로 다시 확인한다."""

from common.geo import Point
from shortlist import routing


def test_compute_routes_empty_input_returns_empty_list():
    assert routing.compute_routes([]) == []


def test_compute_routes_single_pin_has_no_legs_and_zero_distance():
    points = [Point(id="pin_1", lat=35.10, lng=129.00)]
    routes = routing.compute_routes(points)

    assert len(routes) == 1
    assert routes[0].region_label == "구역 1"
    assert routes[0].ordered_pin_ids == ["pin_1"]
    assert routes[0].total_distance_m == 0
    assert routes[0].legs == []


def test_compute_routes_close_pins_merge_into_one_region():
    # 서면(부산) 인근 좌표 3개 — 서로 수백m 이내, DEFAULT_CLUSTER_THRESHOLD_M(3km) 이내로 묶인다.
    points = [
        Point(id="pin_1", lat=35.1580, lng=129.0590),
        Point(id="pin_2", lat=35.1590, lng=129.0600),
        Point(id="pin_3", lat=35.1600, lng=129.0610),
    ]
    routes = routing.compute_routes(points)

    assert len(routes) == 1
    assert set(routes[0].ordered_pin_ids) == {"pin_1", "pin_2", "pin_3"}
    assert len(routes[0].legs) == 2  # 3개 점 = 2개 구간
    assert routes[0].total_distance_m > 0


def test_compute_routes_far_apart_clusters_split_into_separate_regions():
    """완료 정의: "8km 이상 떨어진 두 클러스터 케이스"가 지역별로 별도 동선이 되는지."""
    cluster_a = [
        Point(id="a1", lat=35.1580, lng=129.0590),
        Point(id="a2", lat=35.1585, lng=129.0595),
    ]
    # a1에서 대략 위도 0.08도(약 8.9km) 떨어진 지점 — DEFAULT_CLUSTER_THRESHOLD_M(3km)을 훌쩍 넘는다.
    cluster_b = [
        Point(id="b1", lat=35.2380, lng=129.0590),
        Point(id="b2", lat=35.2385, lng=129.0595),
    ]
    points = cluster_a + cluster_b

    routes = routing.compute_routes(points)

    assert len(routes) == 2
    region_pins = {frozenset(r.ordered_pin_ids) for r in routes}
    assert region_pins == {frozenset({"a1", "a2"}), frozenset({"b1", "b2"})}
    for route in routes:
        assert len(route.legs) == 1  # 각 지역 2개 점 = 1개 구간


def test_compute_routes_legs_use_haversine_distance_and_walk_minutes():
    from common.geo import approx_walk_minutes, haversine_distance_m

    a = Point(id="pin_1", lat=35.10, lng=129.00)
    b = Point(id="pin_2", lat=35.101, lng=129.001)
    routes = routing.compute_routes([a, b])

    leg = routes[0].legs[0]
    expected_distance = haversine_distance_m(a.lat, a.lng, b.lat, b.lng)
    assert leg.distance_m == expected_distance
    assert leg.approx_minutes == approx_walk_minutes(expected_distance)
    assert routes[0].total_distance_m == expected_distance


def test_compute_routes_region_labels_are_numbered_in_input_order():
    cluster_a = [Point(id="a1", lat=35.1580, lng=129.0590)]
    cluster_b = [Point(id="b1", lat=35.2380, lng=129.0590)]

    routes = routing.compute_routes(cluster_a + cluster_b)

    assert routes[0].region_label == "구역 1"
    assert routes[0].ordered_pin_ids == ["a1"]
    assert routes[1].region_label == "구역 2"
    assert routes[1].ordered_pin_ids == ["b1"]

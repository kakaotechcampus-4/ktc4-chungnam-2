"""
동선 계산(5-10) 기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·이벤트는 flows.py가
맡는다.

핀을 거리 임계값으로 묶는 연결 요소 계산은 recommend와 함께 `common.geo.cluster_points`를 쓴다(#274).
동선과 추천의 임계값은 각 호출자가 정한다.
"""

from __future__ import annotations

from common.geo import Point, approx_walk_minutes, cluster_points as _cluster_points, haversine_distance_m, nearest_neighbor_order
from shortlist.schemas import Route, RouteLeg

# 확정 핀들을 "같은 동선"으로 묶을 최대 거리(미터). 도보 기준(common/geo.py의
# WALKING_SPEED_M_PER_MIN=80m/분)으로 약 37분 거리 — 하루 일정 안에서 걸어서 이동할 만한
# 상한으로 잡았다. shortlist/CLAUDE.md 완료 정의의 "8km 이상 떨어진 두 클러스터" 테스트
# 기준보다 충분히 작아 그 케이스는 항상 분리된다. 정확한 수치(3km)는 v1 잠정치이고, 실사용
# 데이터로 조정이 필요하면 여기 상수만 바꾸면 된다(#274).
DEFAULT_CLUSTER_THRESHOLD_M = 3_000


def _build_single_route(points: list[Point], *, region_label: str) -> Route:
    order_ids = nearest_neighbor_order(points)
    by_id = {p.id: p for p in points}

    legs: list[RouteLeg] = []
    total_distance_m = 0.0
    for from_id, to_id in zip(order_ids, order_ids[1:]):
        a, b = by_id[from_id], by_id[to_id]
        distance_m = haversine_distance_m(a.lat, a.lng, b.lat, b.lng)
        legs.append(RouteLeg(
            from_pin_id=from_id, to_pin_id=to_id,
            distance_m=distance_m, approx_minutes=approx_walk_minutes(distance_m),
        ))
        total_distance_m += distance_m

    return Route(region_label=region_label, ordered_pin_ids=order_ids, total_distance_m=total_distance_m, legs=legs)


def compute_routes(points: list[Point], *, cluster_threshold_m: float = DEFAULT_CLUSTER_THRESHOLD_M) -> list[Route]:
    """확정 핀 좌표 목록 → 지역별 동선 목록. 핀이 없으면 빈 리스트(api-spec.yaml GET 계약과 동일).
    지역 하나(핀 1개)짜리 클러스터는 legs가 빈 배열, total_distance_m=0인 동선이 된다."""
    if not points:
        return []
    clusters = _cluster_points(points, cluster_threshold_m)
    return [
        _build_single_route(cluster, region_label=f"구역 {i}")
        for i, cluster in enumerate(clusters, start=1)
    ]

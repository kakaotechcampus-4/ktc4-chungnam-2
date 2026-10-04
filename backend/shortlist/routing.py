"""
동선 계산(5-10) 기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·이벤트는 flows.py가
맡는다.

`shortlist/CLAUDE.md`의 "넘지 말 것"은 원래 지역 클러스터링을 `recommend`의 5-6-1 로직(사람이
쓴 반경 사유끼리 겹치는 원 교집합/합집합)과 같은 공유 유틸로 뽑으라고 했었다. 그런데 이 둘은
사실 다른 문제다 — recommend는 "사람이 선언한 반경(원)들이 겹치는가"를 묻고, 여기는 "이미
확정된 핀들이 걸어서 하나의 동선으로 묶일 만큼 가까운가"를 묻는다. `recommend`에 아직 그런
클러스터링 유틸이 없기도 하다(코드베이스 확인). 이슈 #103에서 루트가 "지역 클러스터링
기준(거리 임계값 등)은 구현하면서 정하되, 근거를 PR에 남겨달라"고 명시적으로 위임해 이 파일
안에 자체 구현했다 — for_Root.md에 근거를 남긴다.
"""

from __future__ import annotations

from common.geo import Point, approx_walk_minutes, haversine_distance_m, nearest_neighbor_order
from shortlist.schemas import Route, RouteLeg

# 확정 핀들을 "같은 동선"으로 묶을 최대 거리(미터). 도보 기준(common/geo.py의
# WALKING_SPEED_M_PER_MIN=80m/분)으로 약 37분 거리 — 하루 일정 안에서 걸어서 이동할 만한
# 상한으로 잡았다. shortlist/CLAUDE.md 완료 정의의 "8km 이상 떨어진 두 클러스터" 테스트
# 기준보다 충분히 작아 그 케이스는 항상 분리된다. 정확한 수치(3km)는 v1 잠정치이고, 실사용
# 데이터로 조정이 필요하면 여기 상수만 바꾸면 된다 — for_Root.md에 별도 확인 요청 남김.
DEFAULT_CLUSTER_THRESHOLD_M = 3_000


def _cluster_points(points: list[Point], threshold_m: float) -> list[list[Point]]:
    """거리 임계값 기준 단일 연결(single-linkage) 클러스터링 — union-find로 연결 요소를 찾는다.
    A-B, B-C가 각각 임계값 이내면 A-C가 임계값을 넘어도 한 클러스터로 묶인다(체이닝). 반환
    순서는 각 클러스터의 대표 점이 `points`에 처음 등장하는 순서를 따른다 — 호출자가 이미
    added_at 오름차순으로 넘기면(shortlist/flows.py) region_label 번호가 매 호출마다 안정적이다.
    """
    n = len(points)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if haversine_distance_m(points[i].lat, points[i].lng, points[j].lat, points[j].lng) <= threshold_m:
                union(i, j)

    groups: dict[int, list[Point]] = {}
    order: list[int] = []
    for i, p in enumerate(points):
        root = find(i)
        if root not in groups:
            groups[root] = []
            order.append(root)
        groups[root].append(p)
    return [groups[root] for root in order]


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

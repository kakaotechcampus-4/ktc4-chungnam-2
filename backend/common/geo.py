"""
좌표 유틸 — 직선거리 계산 + 근사 도보 시간 + 최근접 이웃 순서. 여러 모듈이 공유한다
(backend/common/CLAUDE.md "책임": PostGIS 좌표 유틸). 지금은 `shortlist`의 동선 계산(5-10)이
쓰고, `recommend`의 반경 판정(5-6-1)이 뒤이어 이 파일을 확장할 예정이다.

거리는 항상 직선거리다(13절) — 실제 도로/보행 경로 거리가 아니다. "도보 N분"으로 표기할 때는
반드시 이 파일의 `approx_walk_minutes`를 거쳐서 보정계수(WALKING_SPEED_M_PER_MIN)를 명시적으로
남긴다(최종기획안.md 13절 "표기를 정직하게 하거나 보정계수를 명시한다").
"""

from __future__ import annotations

import math
from typing import NamedTuple, Sequence

EARTH_RADIUS_M = 6_371_000
WALKING_SPEED_M_PER_MIN = 80  # 성인 평균 도보 속도 약 4.8km/h 근사치 — 실측 아님, 근사 표기용 상수


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 직선거리(미터). PostGIS의 geography 캐스트와 같은 구면 근사(WGS84 구 가정)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def approx_walk_minutes(distance_m: float) -> int:
    """직선거리를 "도보 약 N분"으로 근사 표기할 때 쓰는 값. 최소 1분(0분으로 표기하면 도착
    직전처럼 보여 혼동을 준다)."""
    return max(1, round(distance_m / WALKING_SPEED_M_PER_MIN))


class Point(NamedTuple):
    id: str
    lat: float
    lng: float


def nearest_neighbor_order(points: Sequence[Point], *, start_id: str | None = None) -> list[str]:
    """탐욕적 최근접 이웃 순서(모델 미사용 — shortlist/CLAUDE.md "왜 AI 동선 짜주기가 아닌가").
    매 단계에서 아직 안 방문한 점 중 현재 위치에서 가장 가까운 점을 고른다. 최적해를 보장하지
    않는다(NP-hard TSP의 근사) — v1 범위는 "합리적인 순서"면 충분하다(기획안에 최적 경로 요구
    없음).

    `start_id`를 안 주면 첫 번째 점에서 시작한다. 빈 입력은 빈 리스트를 반환한다."""
    if not points:
        return []

    remaining = list(points)
    if start_id is not None:
        start_idx = next(i for i, p in enumerate(remaining) if p.id == start_id)
        current = remaining.pop(start_idx)
    else:
        current = remaining.pop(0)

    order = [current.id]
    while remaining:
        current = min(
            remaining,
            key=lambda p: haversine_distance_m(current.lat, current.lng, p.lat, p.lng),
        )
        remaining.remove(current)
        order.append(current.id)
    return order

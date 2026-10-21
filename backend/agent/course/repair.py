"""도보 위반 재편성 — 한 수씩 고치는 올라가기(optimize.climb)가 막힌 곳을 정확히 푼다. 순수 함수다.

올라가기는 한 수(또는 묶음)씩 고치므로 "구간 상한 안에 이어지는 이웃이 하나도 없는 장소는 그 날 혼자여야 한다" 같은 큰 구조 변화는
못 찾는다. 여기서는 장소 수가 작을 때(큰 묶음 14곳 이하) 가능한 모든 날 배정을 따져서 도보(구간·하루·구성원)와 확인된 휴무를 모두 지키는
코스를 찾는다. 있으면 현재 코스와 가장 덜 달라지는 것을 돌려주고(그 위에서 올라가기를 다시 한다), 없으면 없다는 것을 증명한 것이다.

- 한 날의 장소는 구간 상한(LEG_MAX_MIN) 이하로만 이어지는 한 묶음(연결 성분) 안에 있어야 한다. 묶음 안에서 부분집합마다 최단 방문 순서(비트마스크 DP)를 구한다.
- 부분집합이 하루 상한(구성원 제약 포함)을 넘거나, 그날 쉬는 곳이 있거나, 고정(locks)과 어긋나면 그 날에는 쓸 수 없다.
- 남은 장소 중 번호가 가장 앞선 장소를 어느 날 어느 부분집합에 넣을지로 배정을 나눈다(같은 배정을 두 번 세지 않는다).
영업시간을 모르는 곳은 쉬지 않는다고 본다(없다는 증명을 약하게 만들 뿐 틀리게 만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Optional

from agent.course import core
from agent.course.constants import DAY_TRAVEL_MAX_MIN, LEG_MAX_MIN

REBUILD_MAX_COMPONENT = 14       # 묶음이 이보다 크면 정확한 탐색을 하지 않는다(2^14 부분집합)


@dataclass(frozen=True)
class Rebuild:
    course: Optional[core.Course]
    exhaustive: bool             # True면 끝까지 따졌다 — course가 None이면 "도보·확정 휴무를 모두 지키는 코스는 없다"는 증명이다


def _components(trip: core.Trip) -> list[list[str]]:
    aliases = [p.alias for p in trip.places]
    seen: set[str] = set()
    out: list[list[str]] = []
    for start in aliases:
        if start in seen:
            continue
        comp, stack = [start], [start]
        seen.add(start)
        while stack:
            x = stack.pop()
            for y in aliases:
                if y not in seen and core.travel_minutes(trip, x, y) <= LEG_MAX_MIN:
                    seen.add(y)
                    comp.append(y)
                    stack.append(y)
        out.append(sorted(comp, key=aliases.index))
    return out


def _path_table(trip: core.Trip, comp: list[str]) -> tuple[list[list[float]], list[list[int]]]:
    """부분집합(비트마스크)별·끝 장소별 구간 상한을 지키는 최단 방문 거리와, 순서를 되살릴 부모 표."""
    n = len(comp)
    t = [[core.travel_minutes(trip, a, b) for b in comp] for a in comp]
    near = [[j for j in range(n) if j != i and t[i][j] <= LEG_MAX_MIN] for i in range(n)]
    inf = float("inf")
    dp = [[inf] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]
    for i in range(n):
        dp[1 << i][i] = 0
    for mask in range(1, 1 << n):
        row = dp[mask]
        for last in range(n):
            cost = row[last]
            if cost == inf:
                continue
            for j in near[last]:
                if mask >> j & 1:
                    continue
                nm, c = mask | 1 << j, cost + t[last][j]
                if c < dp[nm][j]:
                    dp[nm][j], parent[nm][j] = c, last
    return dp, parent


def _order(comp: list[str], dp_row: list[float], parent: list[list[int]], mask: int) -> tuple[str, ...]:
    last = min(range(len(comp)), key=lambda j: (dp_row[j], j))
    path = []
    while last != -1:
        path.append(comp[last])
        prev = parent[mask][last]
        mask ^= 1 << last
        last = prev
    return tuple(reversed(path))


def day_limits(trip: core.Trip) -> list[int]:
    out = []
    for i in range(len(trip.days)):
        da = core.day_alias(i)
        out.append(min([DAY_TRAVEL_MAX_MIN, *[c.value for c in trip.member_constraints if c.day in (None, da)]]))
    return out


def rebuild_walk_feasible(
    trip: core.Trip, hours: core.Hours, locks: Mapping[str, str], current: core.Course,
) -> Rebuild:
    comps = _components(trip)
    if max(len(c) for c in comps) > REBUILD_MAX_COMPONENT:
        return Rebuild(None, False)
    n_days = len(trip.days)
    limits = day_limits(trip)
    aliases = [p.alias for p in trip.places]
    index = {a: i for i, a in enumerate(aliases)}                      # 전체 비트마스크 자리
    where = {p: i for i, day in enumerate(current) for p in day}

    # 날마다 쓸 수 있는 (전체 비트마스크, 비용, 순서) — 비용은 현재 코스와 다른 날에 놓인 장소 수
    options: list[dict[int, list[tuple[int, int, tuple[str, ...]]]]] = [dict() for _ in range(n_days)]
    for comp in comps:
        dp, parent = _path_table(trip, comp)
        costs = [min(row) for row in dp]
        n = len(comp)
        for sub in range(1, 1 << n):
            if costs[sub] == float("inf"):
                continue
            members = [comp[k] for k in range(n) if sub >> k & 1]
            order: Optional[tuple[str, ...]] = None
            for d in range(n_days):
                if costs[sub] > limits[d]:
                    continue
                if any(core.status_on(hours, p, trip.days[d]) == "closed" for p in members):
                    continue
                if any(locks.get(p) not in (None, core.day_alias(d)) for p in members):
                    continue
                full = sum(1 << index[p] for p in members)
                shift = sum(where[p] != d for p in members)
                if order is None:
                    order = _order(comp, dp[sub], parent, sub)
                low = min(index[p] for p in members)
                options[d].setdefault(low, []).append((full, shift, order))
    all_mask = (1 << len(aliases)) - 1

    @lru_cache(maxsize=None)
    def best(remaining: int, used: int) -> Optional[tuple[int, tuple]]:
        if remaining == 0:
            return 0, ()
        low = (remaining & -remaining).bit_length() - 1
        found: Optional[tuple[int, tuple]] = None
        for d in range(n_days):
            if used >> d & 1:
                continue
            for full, shift, order in options[d].get(low, ()):
                if full & ~remaining:
                    continue
                rest = best(remaining & ~full, used | 1 << d)
                if rest is None:
                    continue
                cand = (shift + rest[0], ((d, order), *rest[1]))
                if found is None or cand[0] < found[0]:
                    found = cand
        return found

    result = best(all_mask, 0)
    if result is None:
        return Rebuild(None, True)
    days: list[tuple[str, ...]] = [() for _ in range(n_days)]
    for d, order in result[1]:
        days[d] = order
    return Rebuild(tuple(days), True)


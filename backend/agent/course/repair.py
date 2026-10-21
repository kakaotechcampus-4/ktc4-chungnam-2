"""하루 이동 재편성 — 한 수씩 고치는 올라가기(optimize.climb)가 막힌 곳을 정확히 푼다. 순수 함수다.

올라가기는 한 수(또는 묶음)씩 고치므로 "이 장소들은 한 날에 같이 가야 하고 저 장소들은 다른 날이어야 한다" 같은 큰 구조 변화는
못 찾는다. 여기서는 장소 수가 작을 때(14곳 이하) 가능한 모든 날 배정을 따져서 하드 조건(도보 구간 상한·하루 도보 합계·하루 이동 합계·
구성원 도보 상한)과 확인된 휴무를 모두 지키는 코스를 찾는다. 있으면 날 사이 대중교통 구간이 가장 적고(지역을 날마다 모으고) 그다음 날 사이
장소 수가 고르고 그다음 현재 코스와 가장 덜 달라지는 것을 돌려주고(그 위에서 올라가기를 다시 한다), 없으면 없다는 것을 증명한 것이다.

- 한 날의 장소 부분집합마다 (도보 분, 이동 분) 쌍의 파레토 최적 방문 순서를 구한다(비트마스크 DP). 두 상한을 함께 지키는 순서가 있는지 정확히 가린다.
- 부분집합이 하루 상한(구성원 제약 포함)을 넘거나, 그날 쉬는 곳이 있거나, 고정(locks)과 어긋나면 그 날에는 쓸 수 없다.
- 남은 장소 중 번호가 가장 앞선 장소를 어느 날 어느 부분집합에 넣을지로 배정을 나눈다(같은 배정을 두 번 세지 않는다).
영업시간을 모르는 곳은 쉬지 않는다고 본다(없다는 증명을 약하게 만들 뿐 틀리게 만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Optional

from agent.course import core
from agent.course.constants import DAY_TRAVEL_MAX_MIN, DAY_WALK_MAX_MIN, LEG_MAX_MIN, MODE_TRANSIT, MODE_WALK

REBUILD_MAX_COMPONENT = 14       # 묶음이 이보다 크면 정확한 탐색을 하지 않는다(2^14 부분집합)


@dataclass(frozen=True)
class Rebuild:
    course: Optional[core.Course]
    exhaustive: bool             # True면 끝까지 따졌다 — course가 None이면 "하드 조건과 확정 휴무를 모두 지키는 코스는 없다"는 증명이다


def _usable(trip: core.Trip, a: str, b: str) -> bool:
    """한 구간으로 쓸 수 있나 — 하루 이동 상한 안이고, 걷는 구간이면 구간 상한 안."""
    leg = core.leg_between(trip, a, b)
    return leg.minutes <= DAY_TRAVEL_MAX_MIN and (leg.mode == MODE_TRANSIT or leg.minutes <= LEG_MAX_MIN)


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
                if y not in seen and _usable(trip, x, y):
                    seen.add(y)
                    comp.append(y)
                    stack.append(y)
        out.append(sorted(comp, key=aliases.index))
    return out


Entry = tuple[int, int, int, int]       # (도보 분, 이동 분, 앞 장소 위치, 앞 칸의 항목 번호)


def _path_table(trip: core.Trip, comp: list[str]) -> list[list[list[Entry]]]:
    """부분집합(비트마스크)별·끝 장소별로, 하루 도보·이동 상한을 지키며 방문하는 (도보, 이동) 파레토 최적 항목들."""
    n = len(comp)
    legs = [[core.leg_between(trip, a, b) for b in comp] for a in comp]
    near = [[j for j in range(n) if j != i and _usable(trip, comp[i], comp[j])] for i in range(n)]
    dp: list[list[list[Entry]]] = [[[] for _ in range(n)] for _ in range(1 << n)]
    for i in range(n):
        dp[1 << i][i] = [(0, 0, -1, -1)]
    for mask in range(1, 1 << n):
        row = dp[mask]
        for last in range(n):
            for idx, (walk, total, _, _) in enumerate(row[last]):
                for j in near[last]:
                    if mask >> j & 1:
                        continue
                    leg = legs[last][j]
                    w, t = walk + (leg.minutes if leg.mode == MODE_WALK else 0), total + leg.minutes
                    if w > DAY_WALK_MAX_MIN or t > DAY_TRAVEL_MAX_MIN:
                        continue
                    cell = dp[mask | 1 << j][j]
                    if any(cw <= w and ct <= t for cw, ct, _, _ in cell):
                        continue                                  # 이미 더 좋거나 같은 항목이 있다
                    cell[:] = [e for e in cell if not (w <= e[0] and t <= e[1])]
                    cell.append((w, t, last, idx))
    return dp


def _order(comp: list[str], dp: list[list[list[Entry]]], mask: int, last: int, idx: int) -> tuple[str, ...]:
    path = []
    while last != -1:
        path.append(comp[last])
        _, _, prev, prev_idx = dp[mask][last][idx]
        mask ^= 1 << last
        last, idx = prev, prev_idx
    return tuple(reversed(path))


def day_limits(trip: core.Trip) -> list[tuple[int, int]]:
    """날마다 (도보 상한, 이동 상한) — 구성원 제약은 도보 상한에만 건다."""
    out = []
    for i in range(len(trip.days)):
        da = core.day_alias(i)
        out.append((min([DAY_WALK_MAX_MIN, *[c.value for c in trip.member_constraints if c.day in (None, da)]]), DAY_TRAVEL_MAX_MIN))
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

    # 날마다 쓸 수 있는 (전체 비트마스크, 대중교통 구간 수, 장소 수의 제곱, 현재 코스와 다른 날에 놓인 장소 수, 방문 순서).
    # 배정의 비용은 (대중교통 구간 수의 합, 날별 장소 수 제곱의 합, 옮겨지는 장소 수) — 고를 수 있는 배정 중 하루에 한 지역에 가까운 것,
    # 같으면 날 사이가 가장 고른 것, 같으면 현재 코스에서 덜 옮기는 것
    options: list[dict[int, list[tuple[int, int, int, int, tuple[str, ...]]]]] = [dict() for _ in range(n_days)]
    for comp in comps:
        dp = _path_table(trip, comp)
        n = len(comp)
        for sub in range(1, 1 << n):
            entries = [(w, t, last, idx) for last in range(n) for idx, (w, t, _, _) in enumerate(dp[sub][last])]
            if not entries:
                continue
            members = [comp[k] for k in range(n) if sub >> k & 1]
            full = sum(1 << index[p] for p in members)
            low = min(index[p] for p in members)
            for d in range(n_days):
                walk_cap, travel_cap = limits[d]
                fits = [e for e in entries if e[0] <= walk_cap and e[1] <= travel_cap]
                if not fits:
                    continue
                if any(core.status_on(hours, p, trip.days[d]) == "closed" for p in members):
                    continue
                if any(locks.get(p) not in (None, core.day_alias(d)) for p in members):
                    continue
                shift = sum(where[p] != d for p in members)
                _, _, last, idx = min(fits, key=lambda e: (e[1], e[0], e[2]))
                order = _order(comp, dp, sub, last, idx)
                options[d].setdefault(low, []).append((full, core.day_transit_legs(trip, order), len(members) ** 2, shift, order))
    all_mask = (1 << len(aliases)) - 1

    @lru_cache(maxsize=None)
    def best(remaining: int, used: int) -> Optional[tuple[tuple[int, int, int], tuple]]:
        if remaining == 0:
            return (0, 0, 0), ()
        low = (remaining & -remaining).bit_length() - 1
        found: Optional[tuple[tuple[int, int, int], tuple]] = None
        for d in range(n_days):
            if used >> d & 1:
                continue
            for full, transit, squared, shift, order in options[d].get(low, ()):
                if full & ~remaining:
                    continue
                rest = best(remaining & ~full, used | 1 << d)
                if rest is None:
                    continue
                cand = ((rest[0][0] + transit, rest[0][1] + squared, rest[0][2] + shift), ((d, order), *rest[1]))
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


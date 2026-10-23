"""테스트 지도. 서울시청 근처 6곳, 3일(월·화·수). 좌표는 서로 수백 m 안이라 이동 위반은 없다.

도식 2 시나리오용 영업시간: p4(음식점)는 화요일 휴무, p5(카페)는 매일 연다. 그런데 처음 스냅샷에는
두 곳의 영업시간이 없다(결측) — 조회 도구로만 알 수 있다.
"""

from datetime import date

from agent.course.core import Place, Trip
from agent.course.ports import FixtureOpeningHours

MON, TUE, WED = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)
ALL_OPEN = {wd: "open" for wd in range(7)}


def place(alias: str, category: str, lat: float, lng: float, labels=()) -> Place:
    return Place(alias=alias, pin_id=f"pin-{alias}", place_id=f"own-{alias}", name=f"장소{alias.upper()}이름",
                 category=category, lat=lat, lng=lng, labels=frozenset(labels))


PLACES = (
    place("p1", "관광지", 37.5665, 126.9780),
    place("p2", "카페", 37.5670, 126.9790),
    place("p3", "음식점", 37.5680, 126.9800),
    place("p4", "음식점", 37.5685, 126.9810),
    place("p5", "카페", 37.5690, 126.9805),
    place("p6", "관광지", 37.5675, 126.9770, labels=("night_view",)),
)


def trip(**kwargs) -> Trip:
    return Trip(places=kwargs.pop("places", PLACES), days=kwargs.pop("days", (MON, TUE, WED)), **kwargs)


# 처음 코스: 둘째 날(화)에 p3·p4·p5
COURSE = (("p1", "p2"), ("p3", "p4", "p5"), ("p6",))

# 처음 스냅샷에서 아는 영업시간 — p4, p5는 모른다
KNOWN_HOURS = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}

# 조회하면 나오는 실제 영업시간 (place_id 기준)
TRUE_HOURS = FixtureOpeningHours({
    **{f"own-{p}": ALL_OPEN for p in ("p1", "p2", "p3", "p6")},
    "own-p4": {**ALL_OPEN, TUE.weekday(): "closed"},
    "own-p5": ALL_OPEN,
})

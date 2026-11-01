"""하루 식사 장소 — 식당이 없는 날 알림과 식당 고르게 나누기(#918). 시간 배정이 없어 하루 식당 수로 본다."""

from datetime import date

from agent.course import baseline, core, direct, worklog
from agent.course.constants import MEAL_CATEGORY, MEALS_PER_DAY_MAX, MEALS_PER_DAY_MIN
from agent.course.core import Place, Trip
from agent.course.ports import FixtureOpeningHours
from agent.course.state import initial_state
from common.geo import WALKING_SPEED_M_PER_MIN as SPEED

DAYS = (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21))      # 월 화 수
OPEN = {w: "open" for w in range(7)}


def at(alias: str, category: str, east_min: float, north_min: float = 0.0) -> Place:
    return Place(alias, f"pin-{alias}", f"own-{alias}", alias, category,
                 37.5 + north_min * SPEED / 111_195, 127.0 + east_min * SPEED / 88_000)


def cluster(restaurants: int, others: int) -> Trip:
    """한 동네(서로 걸어서 몇 분)에 식당 restaurants곳 + 카페·관광지 others곳."""
    places = [at(f"p{i + 1}", MEAL_CATEGORY, 2 * i) for i in range(restaurants)]
    places += [at(f"p{restaurants + i + 1}", ("카페", "관광지")[i % 2], 2 * (restaurants + i)) for i in range(others)]
    return Trip(places=tuple(places), days=DAYS)


def run(trip: Trip, course):
    hours = {p.alias: OPEN for p in trip.places}
    state = initial_state(trip, hours, course)
    return direct.run_direct(state, decide=None, hours=FixtureOpeningHours({p.place_id: OPEN for p in trip.places}))


def meal_counts(trip, course):
    return core.day_meal_counts(trip, course)


def test_constants_are_one_to_two():
    assert MEALS_PER_DAY_MIN == 1 and MEALS_PER_DAY_MIN <= MEALS_PER_DAY_MAX


def test_두곳_사흘이면_식당_없는_날이_하루뿐이고_알린다():
    trip = cluster(2, 7)
    # 날짜 균형 0, 식당끼리 붙지 않고 한 카테고리뿐인 날도 없다 — 식당 고르게만 움직일 이유다
    result = run(trip, (("p1", "p3", "p2"), ("p4", "p5", "p6"), ("p7", "p8", "p9")))
    assert sorted(meal_counts(trip, result.course)) == [0, 1, 1]
    assert core.meal_cover(trip, result.course) == 0
    lines = worklog.render(trip, (), (), result)
    notices = [l for l in lines if "식사할 곳이 확정 리스트에 없어요" in l]
    missing = core.meal_less_days(trip, result.course)
    assert len(notices) == 1 and len(missing) == 1
    assert notices[0] == f"[확인] 검증(코드) {core.day_label(trip, core.day_alias(missing[0]))}에는 식사할 곳이 확정 리스트에 없어요"
    assert sorted(p for d in result.course for p in d) == sorted(p.alias for p in trip.places)      # 장소를 더하거나 빼지 않는다


def test_세곳_사흘이면_날마다_한곳():
    trip = cluster(3, 6)
    result = run(trip, (("p1", "p4", "p2"), ("p5", "p6", "p7"), ("p3", "p8", "p9")))
    assert meal_counts(trip, result.course) == [1, 1, 1]
    assert core.meal_less_days(trip, result.course) == []
    assert not [l for l in worklog.render(trip, (), (), result) if "식사할 곳이" in l]


def test_여섯곳_사흘이면_하루_두곳_이하이고_연달아_붙지_않는다():
    trip = cluster(6, 3)
    result = run(trip, (("p1", "p2", "p3"), ("p4", "p5", "p6"), ("p7", "p8", "p9")))
    assert max(meal_counts(trip, result.course)) <= MEALS_PER_DAY_MAX and min(meal_counts(trip, result.course)) >= 1
    soft = core.soft_scores(trip, result.course)
    assert soft["meal_per_day"] == 0 and soft["meal_spacing"] == 0


def test_식당이_없으면_채울_수_있었던_날도_없다():
    trip = cluster(0, 4)
    course = (("p1", "p2"), ("p3",), ("p4",))
    assert core.meal_cover(trip, course) == 0 and core.meal_less_days(trip, course) == [0, 1, 2]


def test_meal_cover_counts_only_days_that_could_have_had_a_meal():
    trip = cluster(2, 4)
    assert core.meal_cover(trip, (("p1", "p2", "p3"), ("p4",), ("p5", "p6"))) == 1       # 식당 둘이 한 날에 몰림
    assert core.meal_cover(trip, (("p1", "p3"), ("p2", "p4"), ("p5", "p6"))) == 0


def test_meal_cover_beats_transit_legs_but_not_day_balance(monkeypatch):
    base = {"meal_spacing": 0, "meal_per_day": 0, "cafe_spacing": 0, "cafe_after_meal": None, "night_last": None,
            "mono_category_days": 0, "no_tour_days": None, "travel_total": 0}

    def key(balance, cover, transit):
        monkeypatch.setattr(core, "soft_scores", lambda trip, course: {**base, "day_balance": balance, "meal_cover": cover, "transit_legs": transit})
        return baseline._soft_key(None, ())

    assert key(0, 0, 5) < key(0, 1, 0)       # 식당 고르게가 대중교통 구간보다 먼저
    assert key(0, 5, 5) < key(1, 0, 0)       # 날짜 균형이 식당 고르게보다 먼저

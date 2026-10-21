"""도보 위반 수리 — 날 안 순서 다시 짜기, 한 수씩으로 못 푸는 위반의 재편성, 없다는 증명."""

from datetime import date

from agent.course import baseline, core, optimize as O, repair
from agent.course.core import MemberConstraint, Place, Trip
from agent.course.state import initial_state
from common.geo import WALKING_SPEED_M_PER_MIN as SPEED

DAYS = (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21))
OPEN = {w: "open" for w in range(7)}
CATS = ("음식점", "카페", "관광지")


def at(alias: str, category: str, east_min: float, north_min: float = 0.0) -> Place:
    """기준점에서 동쪽·북쪽으로 도보 몇 분 떨어진 곳(직선거리 기준)."""
    return Place(alias, f"pin-{alias}", f"own-{alias}", alias, category,
                 37.5 + north_min * SPEED / 111_195, 127.0 + east_min * SPEED / 88_000)


# p1~p6은 30분 간격 일렬(이어 걸으면 150분), p7은 아무 데서나 200분 떨어진 외톨이
LINE = tuple(at(f"p{i + 1}", CATS[i % 3], 30 * i) for i in range(6))
LONER = at("p7", "관광지", 0, 200)


def make_trip(days=DAYS, cap=90, places=(*LINE, LONER)) -> Trip:
    return Trip(places=tuple(places), days=days, member_constraints=(MemberConstraint("daily_walk_max", cap, None),))


def state_of(trip: Trip, course):
    return initial_state(trip, {p.alias: OPEN for p in trip.places}, course)


def confirmed(state) -> int:
    return core.hard_score(state.violations)[0]


class TestBestDayOrder:
    def test_reorders_to_remove_a_long_leg(self):
        trip = make_trip(places=LINE[:3])
        assert core.best_day_order(trip, ("p1", "p3", "p2")) in (("p1", "p2", "p3"), ("p3", "p2", "p1"))

    def test_keeps_the_current_order_when_it_is_already_best(self):
        trip = make_trip(places=LINE[:3])
        assert core.best_day_order(trip, ("p3", "p2", "p1")) == ("p3", "p2", "p1")

    def test_is_deterministic_and_a_permutation(self):
        trip = make_trip()
        day = ("p5", "p1", "p3", "p2", "p4")
        a, b = core.best_day_order(trip, day), core.best_day_order(trip, day)
        assert a == b and sorted(a) == sorted(day)

    def test_long_days_still_return_a_permutation_without_getting_worse(self):
        places = tuple(at(f"p{i + 1}", CATS[i % 3], 9 * (i % 6), 9 * (i // 6)) for i in range(12))
        trip = make_trip(places=places)
        day = tuple(p.alias for p in places)
        better = core.best_day_order(trip, day)
        assert sorted(better) == sorted(day) and core.day_travel(trip, better) <= core.day_travel(trip, day)


class TestStrongMoves:
    def test_a_single_move_clears_a_leg_violation_inside_a_day(self):
        trip = make_trip(places=LINE[:3], days=DAYS[:1])
        s = state_of(trip, (("p1", "p3", "p2"),))
        assert confirmed(s) == 1
        move = baseline.strong_best_move(s)
        assert move is not None
        fixed = core.apply_move(trip, s.course, move, s.locks)
        assert core.hard_score(core.find_violations(trip, fixed, s.hours))[0] == 0

    def test_never_picks_a_move_that_adds_confirmed_violations(self):
        trip = make_trip()
        s = state_of(trip, (("p1", "p7", "p4"), ("p6", "p2"), ("p3", "p5")))
        moves = baseline.strong_best_moves(s)
        course = s.course
        for m in moves or ():
            course = core.apply_move(trip, course, m, s.locks)
        assert core.hard_score(core.find_violations(trip, course, s.hours)) < core.hard_score(s.violations)


class TestRebuild:
    START = (("p1", "p7", "p4"), ("p6", "p2"), ("p3", "p5"))

    def test_one_move_at_a_time_gets_stuck_but_rebuild_clears_every_violation(self):
        trip = make_trip()
        s = state_of(trip, self.START)
        assert confirmed(O.climb(s)) > 0                      # 외톨이를 혼자 두려면 여러 장소가 한꺼번에 옮겨야 한다
        done, proven = O.climb_and_rebuild(s)
        assert confirmed(done) == 0 and not proven
        assert [day for day in done.course if "p7" in day] == [("p7",)]                       # 외톨이는 혼자

    def test_rebuild_result_keeps_every_place_once_and_all_limits(self):
        trip = make_trip()
        r = repair.rebuild_walk_feasible(trip, {p.alias: OPEN for p in trip.places}, {}, self.START)
        assert r.exhaustive and r.course is not None
        assert sorted(p for day in r.course for p in day) == sorted(p.alias for p in trip.places)
        assert core.hard_score(core.find_violations(trip, r.course, {p.alias: OPEN for p in trip.places}))[0] == 0

    def test_rebuild_respects_known_closed_days_and_locks(self):
        trip = make_trip()
        hours = {p.alias: OPEN for p in trip.places}
        hours["p7"] = {**OPEN, DAYS[2].weekday(): "closed"}     # 외톨이는 셋째 날 쉰다
        r = repair.rebuild_walk_feasible(trip, hours, {"p1": "d1"}, self.START)
        assert r.course is not None
        assert "p7" not in r.course[2] and "p1" in r.course[0]

    def test_prefers_the_arrangement_closest_to_the_current_course(self):
        trip = make_trip()
        good = (("p1", "p2", "p3"), ("p4", "p5", "p6"), ("p7",))
        r = repair.rebuild_walk_feasible(trip, {p.alias: OPEN for p in trip.places}, {}, good)
        assert r.course is not None and [set(d) for d in r.course] == [set(d) for d in good]


class TestInfeasible:
    """외톨이가 한 날을 통째로 쓰고 나면, 일렬 6곳(150분)이 하루 90분 상한 아래 한 날에 들어갈 수 없다."""
    TWO_DAYS = DAYS[:2]

    def test_exhaustive_search_proves_it_and_says_so(self):
        trip = make_trip(days=self.TWO_DAYS)
        s = state_of(trip, (("p1", "p2", "p3", "p4"), ("p5", "p6", "p7")))
        _, candidates = O.optimize(s, gateway=_NoLookup())
        assert confirmed(s) > 0 and candidates[0].walk_infeasible is True
        assert core.hard_score(candidates[0].violations)[0] > 0        # 상한을 어기는 코스를 "해결"로 내지 않는다

    def test_infeasible_is_not_claimed_when_a_solution_exists(self):
        trip = make_trip()
        s = state_of(trip, (("p1", "p7", "p4"), ("p6", "p2"), ("p3", "p5")))
        _, candidates = O.optimize(s, gateway=_NoLookup())
        assert candidates[0].walk_infeasible is False
        assert core.hard_score(candidates[0].violations)[0] == 0

    def test_cheap_lower_bound_agrees(self):
        assert core.walk_infeasible(make_trip(days=self.TWO_DAYS)) == (3, 2)
        assert core.walk_infeasible(make_trip()) is None

    def test_too_many_places_in_one_cluster_skips_the_exact_search(self):
        places = tuple(at(f"p{i + 1}", CATS[i % 3], 5 * (i % 8), 5 * (i // 8)) for i in range(repair.REBUILD_MAX_COMPONENT + 2))
        trip = make_trip(places=places)
        r = repair.rebuild_walk_feasible(trip, {}, {}, core.draft_course(trip))
        assert r.course is None and r.exhaustive is False


class _NoLookup:
    def get_opening_hours(self, place_ids):       # 모든 장소의 영업시간을 이미 안다 — 조회가 불리지 않는다
        raise AssertionError("조회가 필요 없다")


def test_worklog_says_so_when_infeasibility_is_proven():
    from agent.course import direct, worklog
    trip = make_trip(days=TestInfeasible.TWO_DAYS)
    s = state_of(trip, (("p1", "p2", "p3", "p4"), ("p5", "p6", "p7")))
    result = direct.run_direct(s, decide=None, hours=_NoLookup(), unmatched_count=0)
    lines = worklog.render(trip, (), (), result)
    assert result.outcome == "unresolved"
    assert any("없다는 것을 모든 경우를 따져" in line for line in lines)

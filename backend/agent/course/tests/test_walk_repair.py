"""이동 위반 수리 — 날 안 순서 다시 짜기, 한 수씩으로 못 푸는 위반의 재편성, 없다는 증명(도보·대중교통 구간 모델)."""

from datetime import date

from agent.course import baseline, core, optimize as O, repair
from agent.course.core import MemberConstraint, Place, Trip
from agent.course.state import initial_state
from common.geo import WALKING_SPEED_M_PER_MIN as SPEED

DAYS = (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21))
OPEN = {w: "open" for w in range(7)}
CATS = ("음식점", "카페", "관광지")
SPACING = 15      # 일렬 장소 사이 도보 분(1,200m) — 바로 이웃은 걷고(도보 구간), 한 칸 건너뛰면(2,400m) 대중교통이다


def at(alias: str, category: str, east_min: float, north_min: float = 0.0) -> Place:
    """기준점에서 동쪽·북쪽으로 도보 몇 분 떨어진 곳(직선거리 기준)."""
    return Place(alias, f"pin-{alias}", f"own-{alias}", alias, category,
                 37.5 + north_min * SPEED / 111_195, 127.0 + east_min * SPEED / 88_000)


# p1~p6은 15분 간격 일렬(이어 걸으면 75분), p7은 아주 먼 외톨이(대중교통으로만 닿는다)
LINE = tuple(at(f"p{i + 1}", CATS[i % 3], SPACING * i) for i in range(6))
LONER = at("p7", "관광지", 0, 400)


def make_trip(days=DAYS, cap=60, places=(*LINE, LONER)) -> Trip:
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
    def test_a_single_move_clears_a_day_walk_violation(self):
        trip = make_trip(places=LINE[:4], days=DAYS[:2], cap=30)
        s = state_of(trip, (("p1", "p2", "p3", "p4"), ()))           # 도보 45분 > 구성원 30분
        assert confirmed(s) == 1
        move = baseline.strong_best_move(s)
        assert move is not None
        fixed = core.apply_move(trip, s.course, move, s.locks)
        assert core.hard_score(core.find_violations(trip, fixed, s.hours))[0] == 0

    def test_never_picks_a_move_that_adds_confirmed_violations(self):
        trip = make_trip()
        s = state_of(trip, (("p1", "p2", "p3", "p4", "p5", "p6"), ("p7",), ()))       # 도보 75분 > 60분
        assert confirmed(s) == 1
        moves = baseline.strong_best_moves(s)
        course = s.course
        for m in moves or ():
            course = core.apply_move(trip, course, m, s.locks)
        assert core.hard_score(core.find_violations(trip, course, s.hours)) < core.hard_score(s.violations)

    def test_transit_legs_break_ties_toward_one_area_per_day(self):
        # 요청 목표도 위반도 없을 때 같은 지역끼리 한 날에 모인다: 가까운 둘씩이 먼 장소와 섞이지 않는다
        near = tuple(at(f"n{i}", CATS[i % 3], 3 * i) for i in range(2))
        far = tuple(at(f"f{i}", CATS[(i + 1) % 3], 3 * i, 500) for i in range(2))
        trip = Trip(places=(*near, *far), days=DAYS[:2])
        s = state_of(trip, (("n0", "f0"), ("n1", "f1")))
        done = O.climb(s)
        assert core.course_transit_legs(trip, done.course) == 0
        assert [set(d) for d in done.course] in ([{"n0", "n1"}, {"f0", "f1"}], [{"f0", "f1"}, {"n0", "n1"}])


class TestRebuild:
    START = (("p1", "p2", "p3", "p4", "p5", "p6"), ("p7",), ())

    def test_climb_and_rebuild_clears_every_violation(self):
        trip = make_trip()
        s = state_of(trip, self.START)
        done, proven = O.climb_and_rebuild(s)
        assert confirmed(done) == 0 and not proven

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

    def test_rebuild_keeps_areas_together_so_there_is_no_needless_transit(self):
        trip = make_trip()
        r = repair.rebuild_walk_feasible(trip, {p.alias: OPEN for p in trip.places}, {}, self.START)
        assert r.course is not None and core.course_transit_legs(trip, r.course) == 0

    def test_rebuild_rides_transit_to_keep_the_walk_cap_when_it_must(self):
        # 일렬 6곳이 하루 도보 30분 상한 아래 둘째 날까지 두 날뿐: 걷기만으론 3곳씩(30분)이 한계 — 가능하다
        trip = make_trip(places=LINE, days=DAYS[:2], cap=30)
        r = repair.rebuild_walk_feasible(trip, {p.alias: OPEN for p in trip.places}, {}, (tuple(p.alias for p in LINE), ()))
        assert r.course is not None and core.hard_score(core.find_violations(trip, r.course, {p.alias: OPEN for p in trip.places}))[0] == 0




def far_line(n: int) -> tuple[Place, ...]:
    """30km 간격 일렬 n곳 — 두 곳 사이는 대중교통 약 100분이라 한 날에 둘까지만 들어간다(셋이면 200분 > 하루 이동 180분)."""
    return tuple(Place(f"p{i + 1}", f"pin-p{i + 1}", f"own-p{i + 1}", f"p{i + 1}", CATS[i % 3], 37.0 + 0.27 * i, 127.0) for i in range(n))


class TestInfeasible:
    """멀리 떨어진 5곳은 하루에 둘까지만 들어간다. 이틀로는 4곳이 한계라 없다는 것이 증명된다."""
    TWO_DAYS = DAYS[:2]

    def test_exhaustive_search_proves_it_and_says_so(self):
        trip = Trip(places=far_line(5), days=self.TWO_DAYS)
        s = state_of(trip, (("p1", "p2", "p3"), ("p4", "p5")))
        _, candidates = O.optimize(s, gateway=_NoLookup())
        assert confirmed(s) > 0 and candidates[0].walk_infeasible is True
        assert core.hard_score(candidates[0].violations)[0] > 0        # 상한을 어기는 코스를 "해결"로 내지 않는다

    def test_infeasible_is_not_claimed_when_a_solution_exists(self):
        trip = Trip(places=far_line(5), days=DAYS)
        s = state_of(trip, (("p1", "p2", "p3"), ("p4", "p5"), ()))
        _, candidates = O.optimize(s, gateway=_NoLookup())
        assert candidates[0].walk_infeasible is False
        assert core.hard_score(candidates[0].violations)[0] == 0

    def test_the_old_walking_only_proof_no_longer_applies(self):
        # 일렬 6곳은 도보 30분 상한에서 이틀로 짤 수 있다(걷는 3곳씩 또는 대중교통으로 건너뛰기) — 예전 증명이 말하던 "3일 필요"는 사라졌다
        trip = make_trip(places=LINE, days=self.TWO_DAYS, cap=30)
        r = repair.rebuild_walk_feasible(trip, {p.alias: OPEN for p in trip.places}, {}, (tuple(p.alias for p in LINE), ()))
        assert r.course is not None

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
    trip = Trip(places=far_line(5), days=TestInfeasible.TWO_DAYS)
    s = state_of(trip, (("p1", "p2", "p3"), ("p4", "p5")))
    result = direct.run_direct(s, decide=None, hours=_NoLookup(), unmatched_count=0)
    lines = worklog.render(trip, (), (), result)
    assert result.outcome == "unresolved"
    assert any("없다는 것을 모든 경우를 따져" in line for line in lines)

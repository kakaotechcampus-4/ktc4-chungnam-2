"""코어와 도구 — 초안 배치, 위반 판정 경계, 부드러운 목표, 수리 검사, 도구 오류(명세 19절 2~5번)."""

from dataclasses import replace

import pytest

from agent.course import core, tools
from agent.course.constants import DAY_TRAVEL_MAX_MIN, LEG_MAX_MIN, MAX_LIVE_TRIALS, TOOL_LIMITS
from agent.course.core import MemberConstraint
from agent.course.ports import FixtureOpeningHours
from agent.course.schemas import (
    CommitMove,
    EstimateTravel,
    FindOpenDays,
    GetOpeningHours,
    MoveDay,
    ReorderDay,
    Revert,
    Swap,
    TryMove,
)
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, COURSE, KNOWN_HOURS, MON, PLACES, TRUE_HOURS, TUE, place, trip

OPEN = {p.alias: ALL_OPEN for p in PLACES}


def try_(state, move):
    return tools.execute(TryMove(tool="try_move", move=move), state, TRUE_HOURS)


class TestDraft:
    def test_same_input_same_course(self):
        assert core.draft_course(trip()) == core.draft_course(trip())

    def test_one_area_is_split_by_daily_cap(self):
        # 6곳이 전부 3km 안이라 한 묶음이지만 하루 상한(6÷3일=2곳)을 넘으면 가까운 순으로 나눈다
        course = core.draft_course(trip())
        assert sorted(len(d) for d in course) == [2, 2, 2]
        assert sorted(p for d in course for p in d) == [f"p{i}" for i in range(1, 7)]

    def test_daily_cap_rounds_up_and_small_clusters_stay_whole(self):
        # 7곳 ÷ 3일 = 올림 3곳. 한 묶음(7곳)을 3·3·1로 자르되 하루 상한은 안 넘는다
        seven = PLACES + (place("p7", "카페", 37.5688, 126.9795),)
        course = core.draft_course(trip(places=seven))
        assert max(len(d) for d in course) == 3 and sorted(len(d) for d in course) == [1, 3, 3]

    def test_far_areas_go_to_different_days(self):
        far = (place("q1", "관광지", 37.5665, 126.9780), place("q2", "카페", 37.5670, 126.9790),
               place("q3", "관광지", 37.4979, 127.0276))   # 강남, 약 10km
        course = core.draft_course(trip(places=far, days=(MON, MON.replace(day=20))))
        assert course == (("q1", "q2"), ("q3",))

    def test_day_trip(self):
        assert len(core.draft_course(trip(days=(MON,)))) == 1


class TestViolations:
    def test_unknown_hours_are_not_open(self):
        vs = core.find_violations(trip(), COURSE, KNOWN_HOURS)
        assert {(v.id, v.status) for v in vs} == {("closed:p4:d2", "unknown"), ("closed:p5:d2", "unknown")}

    def test_leg_limit_boundary(self):
        # 위도 0.001도 ≈ 111m. 도보 80m/분 기준으로 상한 바로 아래와 위
        def far_pair(minutes):
            dlat = minutes * 80 / 111_000
            return (place("a", "관광지", 37.5, 127.0), place("b", "관광지", 37.5 + dlat, 127.0))

        for minutes, expected in ((LEG_MAX_MIN, 0), (LEG_MAX_MIN + 1, 1)):
            t = trip(places=far_pair(minutes), days=(MON,))
            vs = core.find_violations(t, (("a", "b"),), {"a": ALL_OPEN, "b": ALL_OPEN})
            assert sum(v.id.startswith("leg:") for v in vs) == expected, minutes

    def test_day_total_and_member_limit(self):
        # 35분 구간 다섯 개 = 175분 > 하루 상한, 구성원 제약(100분)도 걸린다
        step = 35 * 80 / 111_000
        ps = tuple(place(f"x{i}", "관광지", 37.5 + step * i, 127.0) for i in range(6))
        t = trip(places=ps, days=(MON,), member_constraints=(MemberConstraint("daily_walk_max", 100),))
        vs = core.find_violations(t, (tuple(p.alias for p in ps),), {p.alias: ALL_OPEN for p in ps})
        assert {v.id for v in vs} == {"day:d1", "member:d1"}
        assert next(v for v in vs if v.id == "day:d1").detail["limit"] == DAY_TRAVEL_MAX_MIN


class TestSoft:
    def test_scores(self):
        s = core.soft_scores(trip(), COURSE)
        assert s["meal_spacing"] == 1          # p3, p4 연달아
        assert s["cafe_after_meal"] == 0.5     # p5는 p4 다음, p2는 p1 다음
        assert s["night_last"] == 1.0          # p6이 셋째 날 마지막
        assert s["day_balance"] == 2
        assert s["mono_category_days"] == 0    # 한 곳뿐인 셋째 날은 세지 않는다
        assert s["no_tour_days"] == 1          # 둘째 날(p3·p4·p5)에 관광지가 없다

    def test_cafe_spacing_counts_consecutive_cafes(self):
        t = trip()
        assert core.soft_scores(t, (("p2", "p5"), ("p1", "p3"), ("p4", "p6")))["cafe_spacing"] == 1
        assert core.soft_scores(t, (("p2", "p1", "p5"), ("p3",), ("p4", "p6")))["cafe_spacing"] == 0
        # 위치 고르기도 카페가 붙는 자리를 피한다: 카페 p2를 [p5(카페), p1]에 넣으면 p5 바로 앞·뒤(0·1)는 피한다
        assert core.best_position(t, ("p5", "p1"), "p2") == 2

    def test_mono_category_days_boundary(self):
        t = trip()
        # 둘 이상이 한 카테고리: 센다. 둘 이상이어도 섞이면 안 센다. 한 곳뿐이면 안 센다
        assert core.soft_scores(t, (("p3", "p4"), ("p1", "p2"), ("p5", "p6")))["mono_category_days"] == 1
        assert core.soft_scores(t, (("p3",), ("p1", "p2"), ("p4", "p5", "p6")))["mono_category_days"] == 0
        assert core.soft_scores(t, (("p2", "p5"), ("p3", "p4"), ("p1", "p6")))["mono_category_days"] == 3

    def test_no_tour_days_ignores_empty_days_and_none_without_tour(self):
        t = trip()
        assert core.soft_scores(t, (("p1", "p2", "p3", "p4", "p5", "p6"), (), ()))["no_tour_days"] == 0
        assert core.soft_scores(t, (("p2", "p3"), ("p4", "p5"), ("p1", "p6")))["no_tour_days"] == 2
        no_tour = trip(places=PLACES[1:5], days=(MON,))
        assert core.soft_scores(no_tour, (("p2", "p3", "p4", "p5"),))["no_tour_days"] is None

    def test_none_when_no_target(self):
        s = core.soft_scores(trip(places=PLACES[:1], days=(MON,)), (("p1",),))
        assert s["cafe_after_meal"] is None and s["night_last"] is None


class TestMoves:
    def setup_method(self):
        self.state = initial_state(trip(), OPEN, COURSE)

    def test_move_day_position_avoids_meal_clumps(self):
        # 첫째 날 [p3(식당), p1, p2]에 식당 p4를 넣는다. p3 바로 앞·뒤(자리 0·1)는 식당이 붙으니 피한다
        course = (("p3", "p1", "p2"), ("p4",), ("p5", "p6"))
        pos = core.best_position(trip(), ("p3", "p1", "p2"), "p4")
        assert pos in (2, 3)
        new = core.apply_move(trip(), course, MoveDay(type="move_day", place="p4", to_day="d1", position=None), {})
        assert core.soft_scores(trip(), new)["meal_spacing"] == 0

    def test_move_day_position_avoids_exceeding_daily_meals(self):
        # 하루에 식당이 이미 둘이면 식당을 더 넣는 건 피할 수 없다 — 그래도 서로 붙지 않는 자리를 고른다
        pos = core.best_position(trip(), ("p3", "p1", "p6"), "p4")
        assert pos in (2, 3) and pos != 1

    def test_reorder_must_be_permutation(self):
        _, r = try_(self.state, ReorderDay(type="reorder_day", day="d2", places=["p3", "p4"]))
        assert (r.ok, r.error) == (False, "INVALID_MOVE")

    def test_unknown_alias(self):
        _, r = try_(self.state, Swap(type="swap", a="p1", b="p99"))
        assert r.error == "INVALID_ID"

    def test_day_out_of_range(self):
        _, r = try_(self.state, MoveDay(type="move_day", place="p1", to_day="d9"))
        assert r.error == "INVALID_ID"

    def test_lock(self):
        locked = replace(self.state, locks={"p4": "d2"})
        _, r = try_(locked, MoveDay(type="move_day", place="p4", to_day="d3"))
        assert r.error == "LOCKED"
        _, r = try_(locked, Swap(type="swap", a="p4", b="p6"))
        assert r.error == "LOCKED"
        _, r = try_(locked, Swap(type="swap", a="p3", b="p4"))   # 같은 날 안에서는 된다
        assert r.ok

    def test_trial_does_not_change_state(self):
        state, r = try_(self.state, MoveDay(type="move_day", place="p4", to_day="d3"))
        assert r.ok and state.course == COURSE and len(state.trials) == 1


class TestCommitRevert:
    def test_commit_that_adds_confirmed_violation_is_refused(self):
        closed_tue = {**OPEN, "p1": {**ALL_OPEN, 1: "closed"}}
        state = initial_state(trip(), closed_tue, COURSE)
        state, r = try_(state, MoveDay(type="move_day", place="p1", to_day="d2"))
        assert r.data["hard_after"] == {"confirmed": 1, "unknown": 0}
        _, r = tools.execute(CommitMove(tool="commit_move", trial_id=r.data["trial_id"]), state, TRUE_HOURS)
        assert (r.ok, r.error) == (False, "WORSENS_HARD")

    def test_commit_then_revert(self):
        state = initial_state(trip(), OPEN, COURSE)
        state, r = try_(state, MoveDay(type="move_day", place="p4", to_day="d3"))
        state, r = tools.execute(CommitMove(tool="commit_move", trial_id="t1"), state, TRUE_HOURS)
        assert r.data["step"] == 1 and state.course != COURSE and state.trials == ()
        state, r = tools.execute(Revert(tool="revert", to_step=0), state, TRUE_HOURS)
        assert state.course == COURSE and len(state.history) == 3

    def test_no_such_trial(self):
        state = initial_state(trip(), OPEN, COURSE)
        _, r = tools.execute(CommitMove(tool="commit_move", trial_id="t7"), state, TRUE_HOURS)
        assert r.error == "NO_SUCH_TRIAL"


class TestToolLimits:
    def test_per_tool_limit(self):
        state = initial_state(trip(), OPEN, COURSE)
        call = EstimateTravel(tool="estimate_travel", from_place="p1", to_place="p2")
        for _ in range(TOOL_LIMITS["estimate_travel"]):
            state, r = tools.execute(call, state, TRUE_HOURS)
            assert r.ok
        _, r = tools.execute(call, state, TRUE_HOURS)
        assert r.error == "LIMIT_EXCEEDED"

    def test_live_trial_limit(self):
        state = initial_state(trip(), OPEN, COURSE)
        for i in range(MAX_LIVE_TRIALS):
            state, r = try_(state, Swap(type="swap", a="p1", b=f"p{i + 2}"))
            assert r.ok
        _, r = try_(state, Swap(type="swap", a="p1", b="p6"))
        assert r.error == "LIMIT_EXCEEDED"

    def test_lookup_never_overwrites_known_with_unknown(self):
        # p4는 시작 때 모른다. 조회가 빈손이어도(None) 이미 아는 요일은 그대로다
        hours = {**OPEN, "p4": {TUE.weekday(): "closed"}}
        state = initial_state(trip(), hours, COURSE)
        state, r = tools.execute(GetOpeningHours(tool="get_opening_hours", place="p4"), state, FixtureOpeningHours({}))
        assert r.ok and state.hours["p4"] == {TUE.weekday(): "closed"}

    def test_fully_known_place_is_looked_up_from_the_start(self):
        state = initial_state(trip(), KNOWN_HOURS, COURSE)
        assert state.looked_up == {"p1", "p2", "p3", "p6"}       # p4·p5는 모른다 — 조회할 수 있다
        _, r = tools.execute(GetOpeningHours(tool="get_opening_hours", place="p1"), state, TRUE_HOURS)
        assert r.ok and r.data["memo"] == "이미 조회한 결과" and r.data["days"] == {"d1": "open", "d2": "open", "d3": "open"}
        assert state.tool_counts.get("get_opening_hours", 0) == 0
        state, r = tools.execute(GetOpeningHours(tool="get_opening_hours", place="p4"), state, TRUE_HOURS)
        assert r.ok

    def test_find_open_days_twice_returns_stored_answer(self):
        state = initial_state(trip(), OPEN, COURSE)
        call = FindOpenDays(tool="find_open_days", place="p1")
        state, first = tools.execute(call, state, TRUE_HOURS)
        assert first.ok
        # 사이에 다른 호출이 끼어도 저장된 답을 돌려준다. 횟수는 쓰지 않는다
        state, _ = tools.execute(FindOpenDays(tool="find_open_days", place="p2"), state, TRUE_HOURS)
        used = state.tool_counts["find_open_days"]
        state, second = tools.execute(call, state, TRUE_HOURS)
        assert second.ok and second.data["memo"] == "이미 조회한 결과" and second.data["open"] == first.data["open"]
        assert state.tool_counts["find_open_days"] == used


class TestThought:
    def setup_method(self):
        self.trip = trip()

    @pytest.mark.parametrize("text,problem", [
        ("{p4}는 {d2}에 쉬어요", None),
        ("2번째 수를 볼게요", "슬롯 밖 숫자"),
        ("{p9}로 갈게요", "없는 장소 p9"),
        ("{d4}로 옮겨요", "없는 날짜 d4"),
        ("이 장소는 빼세요", "금지 표현"),
        ("", "빈 문장"),
    ])
    def test_problem(self, text, problem):
        assert core.thought_problem(self.trip, text) == problem

    def test_render(self):
        assert core.render_thought(self.trip, "{p4}는 {d2}에 쉬어요") == "장소P4이름는 둘째 날 (화)에 쉬어요"

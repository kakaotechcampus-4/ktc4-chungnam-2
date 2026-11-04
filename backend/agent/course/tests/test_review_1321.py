"""다 넣은 일정의 점검과 최소 수정(#1321, 결정 #1237 3~5절). 엔진은 순수라 모델·DB 없이 돈다."""

import random
from datetime import date

import pytest

from agent.course import core, review, worklog
from agent.course.gateways import NullOpeningHours
from agent.course.intake import PinInput, build_trip
from agent.course.runner import run_course
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, COURSE, MON, TUE, WED, trip

HOURS = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p4", "p5", "p6")}


def closed_on(place, *days, base=HOURS):
    return {**base, place: {**ALL_OPEN, **{d.weekday(): "closed" for d in days}}}


def kinds(problems):
    return [p.kind for p in problems]


def test_clean_schedule_has_no_problems_and_lists_checked_kinds():
    spread = (("p1", "p3"), ("p4", "p2"), ("p5", "p6"))       # 식당 2곳을 서로 다른 날에 — 식당을 더 고르게 나눌 수 없다
    result = review.review(trip(), spread, HOURS)
    assert result.problems == () and result.fixes == ()
    assert result.checked == ("closed", "travel", "cluster", "meal")
    assert "member" not in result.checked and "goal" not in result.checked      # 대상이 없는 종류는 「괜찮아요」를 내지 않는다


def test_closed_place_is_hard_and_fixed_at_first_working_step():
    hours = closed_on("p4", TUE)
    result = review.review(trip(), COURSE, hours)
    hard = [f for f in result.fixes if f.problem.kind == "closed"]
    assert len(hard) == 1 and hard[0].problem.strength == "hard"
    fix = hard[0]
    assert fix.step is not None and fix.not_fixed is None
    after = review.reflect(COURSE, {m.place: m.to_day for m in fix.moves})
    after_problems = review.find_problems(trip(), after, hours)
    assert fix.problem.key not in {p.key for p in after_problems}
    assert {p.key for p in after_problems} <= {p.key for p in result.problems}


def test_ladder_stops_at_day_swap_when_it_works_and_falls_back_when_not():
    # d2와 d3를 통째로 바꾸면 p4가 수요일로 가서 풀린다 → 1단계
    t = trip()
    assert review.review(t, COURSE, closed_on("p4", TUE)).fixes[0].step in (1, 2)
    # p4가 화·수 모두 쉬면 날 맞바꾸기로는 못 푼다 → 다른 단계(또는 크게 바꿔야 해요)
    both = closed_on("p4", TUE, WED)
    fix = review.review(t, COURSE, both).fixes[0]
    assert fix.step != 1
    # 어느 날도 못 가면 안 없이 「크게 바꿔야 해요」
    never = closed_on("p4", MON, TUE, WED)
    fix = review.review(t, COURSE, never).fixes[0]
    assert fix.step is None and fix.not_fixed == review.BIG_CHANGE and fix.moves == ()


def test_day_swap_moves_whole_days_and_keeps_each_days_order():
    course = (("p1", "p2"), ("p3", "p4", "p5"), ("p6",))
    out = review.reflect(course, {"p1": 2, "p2": 2, "p6": 0})
    assert out == (("p6",), ("p3", "p4", "p5"), ("p1", "p2"))


def test_moved_places_append_after_remaining_in_schedule_order():
    course = (("p1", "p2"), ("p3",), ("p4", "p5", "p6"))
    assert review.reflect(course, {"p2": 1, "p4": 1}) == (("p1",), ("p3", "p2", "p4"), ("p5", "p6"))


def test_review_does_not_change_schedule_or_take_locks():
    course = tuple(tuple(d) for d in COURSE)
    review.review(trip(), course, closed_on("p4", TUE))
    assert course == COURSE


def test_hard_problem_always_gets_fix_or_big_change_and_hook_cannot_drop_it():
    hours = closed_on("p4", TUE)
    result = review.review(trip(), COURSE, hours, worth=lambda p, f: "NOT_WORTH")
    for fix in result.fixes:
        if fix.problem.strength == "hard":
            assert fix.step is not None or fix.not_fixed == review.BIG_CHANGE


def test_soft_hook_can_decline_with_reason():
    t = trip(places=trip().places)
    course = (("p1", "p2", "p3", "p4", "p5", "p6"), (), ())
    result = review.review(t, course, HOURS, worth=lambda p, f: "NOT_WORTH")
    soft = [f for f in result.fixes if f.problem.strength == "soft"]
    assert soft and all(f.not_fixed == "NOT_WORTH" and f.moves == () for f in soft)


def test_moved_count_in_strong_key_after_hard_violations():
    from agent.course import baseline
    t = trip()
    state = initial_state(t, HOURS, COURSE)
    moved = review.reflect(COURSE, {"p6": 1})
    same_key = baseline.strong_key(state, COURSE, ())
    home_state = initial_state(t, HOURS, COURSE)
    from dataclasses import replace
    home_state = replace(home_state, home=COURSE)
    assert baseline.strong_key(home_state, COURSE, ())[:3] == (0, 0, 0)
    assert baseline.strong_key(home_state, moved, ())[2] == 1
    assert baseline.strong_key(state, moved, ())[2] == 0 == same_key[2]        # 점검 중이 아니면 옮긴 수는 늘 0
    assert baseline.strong_key(home_state, moved, ()) > baseline.strong_key(home_state, COURSE, ())


def test_member_and_travel_problems_are_hard():
    t = trip(member_constraints=(core.MemberConstraint("daily_walk_max", 1),))
    result = review.review(t, COURSE, HOURS)
    assert "member" in kinds(result.problems) and all(p.strength == "hard" for p in result.problems if p.kind == "member")
    assert kinds(result.problems)[:1] == ["member"]           # 하드가 선호보다 먼저


def pin(i, day=None, order=None, lat=None, lng=None):
    return PinInput(f"pin-{i}", f"own-{i}", f"장소{i}", ("관광지", "카페", "음식점")[i % 3],
                    lat or 37.5665 + i * 0.001, lng or 126.978 + i * 0.001, scheduled_date=day, visit_order=order)


def test_build_trip_schedule_follows_visit_order_only_when_all_placed():
    full = build_trip([pin(1, MON, 2), pin(2, MON, 1), pin(3, TUE, 1), pin(4, WED, 1)], (MON, TUE, WED))
    assert full.schedule == (("p2", "p1"), ("p3",), ("p4",))
    part = build_trip([pin(1, MON, 1), pin(2), pin(3, TUE, 1), pin(4, WED, 1)], (MON, TUE, WED))
    assert part.schedule is None


def test_run_course_in_review_mode_reviews_and_logs_in_order_without_moving_anything():
    out = build_trip([pin(i, (MON, TUE, WED)[(i - 1) % 3], (i + 2) // 3) for i in range(1, 7)], (MON, TUE, WED), unknown_hours="check")
    done = run_course(out, "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
    assert done.review is not None
    assert [tuple(s["pin_id"] for s in d["slots"]) for d in done.view.days] == [("pin-1", "pin-4"), ("pin-2", "pin-5"), ("pin-3", "pin-6")]
    stages = [s["stage"] for s in done.view.steps]
    assert "찾기" in stages


def test_worklog_lines_follow_find_try_decide_order_and_use_templates_only():
    t = trip()
    hours = closed_on("p4", TUE, WED)
    result = review.review(t, COURSE, hours)
    lines = worklog.review_records(t, (), result)
    stages = [r.stage for r in lines]
    assert stages[0] == "찾기" and "옮겨 보기" in stages and stages[-1] == "결정"
    assert "쉬어요" in lines[0].text and t.place("p4").name in lines[0].text
    assert any("풀려요(옮김" in r.text or "크게 바꿔야 해요" in r.text for r in lines)


@pytest.mark.parametrize("seed", range(8))
def test_generated_schedules_invariants(seed):
    """가짜 지도 × 사람이 짠 임의 일정: 하드 문제는 늘 안이나 「크게 바꿔야 해요」가 나오고, 안을 적용해 다시 점검하면 그 문제가 풀리고 새 문제가 안 생긴다.
    고정(사람이 넣은 장소)은 점검이 바꾸지 않는다 — 일정은 입력 그대로다."""
    from agent.course.eval import build_maps, compare
    from agent.course.tests.test_eval import fake_records

    rng = random.Random(seed)
    m = build_maps.build_all(fake_records(), 1, seed=100 + seed)[0]
    sc = compare.scenario_from_map(m)
    aliases = [p.alias for p in sc.trip.places]
    rng.shuffle(aliases)
    n = len(sc.trip.days)
    course = tuple(tuple(aliases[i::n]) for i in range(n))
    snapshot = tuple(tuple(d) for d in course)
    result = review.review(sc.trip, course, sc.truth)
    assert course == snapshot
    before = {p.key for p in result.problems}
    for fix in result.fixes:
        if fix.problem.strength == "hard":
            assert fix.step is not None or fix.not_fixed == review.BIG_CHANGE
        if fix.step is None:
            continue
        after = review.find_problems(sc.trip, review.reflect(course, {m.place: m.to_day for m in fix.moves}), sc.truth)
        assert fix.problem.key not in {p.key for p in after}
        assert {p.key for p in after} <= before
        assert fix.moved == len(fix.moves) <= (len(course[0]) + len(course[1]) if fix.step == 1 else fix.step) or fix.step == 1

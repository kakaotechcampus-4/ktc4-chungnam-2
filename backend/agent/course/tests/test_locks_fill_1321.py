"""사람이 일정에 넣은 장소를 고정하고(locks) 남은 곳만 채운다(#1321, 결정 #1237). 모델은 스텁 planner다."""

from dataclasses import replace
from datetime import date

import pytest

from agent.course import core
from agent.course.gateways import NullOpeningHours
from agent.course.intake import MODE_FILL, MODE_PLAN, MODE_REVIEW, PinInput, build_trip
from agent.course.runner import run_course
from agent.course.state import initial_state
from agent.course.tests.fixtures import MON, TUE, WED
from agent.course.tests.test_runner import direct_planner, goals_planner


def pin(i, day=None, lat=None, lng=None):
    return PinInput(f"pin-{i}", f"own-{i}", f"장소{i}", ("관광지", "카페", "음식점")[i % 3],
                    lat if lat is not None else 37.5665 + i * 0.001, lng if lng is not None else 126.978 + i * 0.001,
                    scheduled_date=day)


def build(pins, days=(MON, TUE, WED)):
    return build_trip(pins, days, unknown_hours="check")


def test_mode_by_schedule_state():
    assert build([pin(i) for i in range(1, 7)]).mode == MODE_PLAN
    assert build([pin(1, MON), *[pin(i) for i in range(2, 7)]]).mode == MODE_FILL
    assert build([pin(i, MON) for i in range(1, 7)]).mode == MODE_REVIEW


def test_locks_use_aliases_and_ignore_dates_outside_trip_or_unroutable():
    live = PinInput("live-1", None, "실시간", "음식점", scheduled_date=MON)
    out = build([pin(1, TUE), pin(2, date(2027, 1, 1)), live, *[pin(i) for i in range(3, 7)]])
    assert dict(out.locks) == {"p1": "d2"}      # 기간 밖 날짜와 좌표 없는 핀은 고정하지 않는다
    assert out.mode == MODE_FILL


def test_plan_mode_draft_unchanged():
    out = build([pin(i) for i in range(1, 7)])
    assert core.draft_course(out.trip, out.locks) == core.draft_course(out.trip)


def test_fill_draft_keeps_locks_and_puts_unassigned_near_locked_day():
    far = dict(lat=37.70, lng=127.10)
    pins = [pin(1, MON), pin(2), pin(3, WED, **far), pin(4, **far)]
    out = build(pins)
    course = core.draft_course(out.trip, out.locks)
    placed = {a: i for i, d in enumerate(course) for a in d}
    assert placed["p1"] == 0 and placed["p3"] == 2
    assert placed["p2"] == 0 and placed["p4"] == 2      # 가까운 날에 둔다(빈 둘째 날이 아니라)


def test_initial_state_rejects_course_that_breaks_lock():
    out = build([pin(1, MON), *[pin(i) for i in range(2, 7)]])
    bad = (("p2", "p3", "p4"), ("p1", "p5"), ("p6",))
    with pytest.raises(ValueError):
        initial_state(out.trip, {}, bad, locks=out.locks)


@pytest.mark.parametrize("scheduled", [{1: MON, 2: TUE}, {1: WED, 3: WED, 4: MON}, {i: (MON, TUE, WED)[i % 3] for i in range(1, 7)}])
def test_run_never_moves_locked_places(scheduled):
    out = build([pin(i, scheduled.get(i)) for i in range(1, 7)])
    result = run_course(out, "둘째 날은 실내 위주로 가고 싶어요", goals_planner=goals_planner, direct_planner=direct_planner(),
                        gateway=NullOpeningHours(), map_items=())
    day_of = {}
    for d in result.view.days:
        for slot in d["slots"]:
            day_of[slot["pin_id"]] = d["date"]
    for i, day in scheduled.items():
        assert str(day_of[f"pin-{i}"]) == str(day)


def test_generated_maps_keep_locks_through_baseline_loop():
    """지도 여러 개(평가 도구가 만든 가짜 지도)에서 일부 장소를 고정하고 기준선 루프를 끝까지 돌려도 고정은 그 날에 남는다."""
    import random
    from agent.course import loop
    from agent.course.eval import build_maps, compare
    from agent.course.tests.test_eval import fake_records

    rng = random.Random(3)
    for m in build_maps.build_all(fake_records(), 6, seed=11):
        sc = compare.scenario_from_map(m)
        aliases = [p.alias for p in sc.trip.places]
        locks = {a: core.day_alias(rng.randrange(len(sc.trip.days))) for a in rng.sample(aliases, len(aliases) // 3)}
        state = initial_state(sc.trip, sc.start_hours, locks=locks)
        for policy in (None, __import__("agent.course.baseline", fromlist=["x"]).next_action_strong):
            kwargs = {"policy": policy} if policy else {}
            done = loop.run_loop(state, decide=None, hours=sc.gateway, **kwargs)
            for alias, day in locks.items():
                assert core.day_alias(core.locate(done.best_course, alias)[0]) == day

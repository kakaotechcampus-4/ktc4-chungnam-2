"""서비스 경로의 엔진 묶음(runner.run_course)과 화면용 결과(result.build_view) — 모델은 스텁 planner다(실호출 없음).

영업시간 게이트웨이는 서비스와 같은 NullOpeningHours(전부 모름)다 — 모든 장소가 「확인 필요」로 남고 위반으로 세지 않는다.
"""

from datetime import date

from agent.course import core
from agent.course.gateways import CourseLlm, NullOpeningHours, get_course_llm
from agent.course.intake import PinInput, build_trip
from agent.course.result import parse_steps, violation_text
from agent.course.runner import run_course, start_hours
from agent.course.tests.fixtures import MON, TUE, WED
from llm.client import LlmCallError
from llm.schemas import CourseDirectTurn, CourseGoal, CourseGoalSet

TEXT = "둘째 날은 실내 위주로 가고 싶어요, 웨이팅 없는 곳으로"


def pins(n=6, live=0):
    base = [
        PinInput(f"pin-{i}", f"own-{i}", f"장소{i}", ("관광지", "카페", "음식점")[i % 3], 37.5665 + i * 0.001, 126.978 + i * 0.001,
                 frozenset({"is_indoor"}) if i % 2 == 0 else frozenset())
        for i in range(1, n + 1)
    ]
    return base + [PinInput(f"live-{i}", None, "실시간", "음식점") for i in range(live)]


def build(n=6, live=0, constraints=()):
    return build_trip(pins(n, live), (MON, TUE, WED), constraints, unknown_hours="check")


def goals_planner(_input):
    return CourseGoalSet(
        goals=[CourseGoal(kind="day_indoor", day="d2", places=[], source="request", quote="둘째 날은 실내 위주로 가고 싶어요")],
        unmatched=["웨이팅 없는 곳으로"],
    )


def direct_planner():
    queue = [
        {"thought": "목표에 맞춰 짜 볼게요", "action": {"tool": "optimize", "priority": ["day_indoor:d2"], "locks": []}},
        {"thought": "첫 후보로 끝낼게요", "action": {"tool": "finish", "candidate_id": "c1"}},
    ]

    def planner(_input):
        return CourseDirectTurn.model_validate(queue.pop(0))

    return planner


class TestNullOpeningHours:
    def test_everything_unknown(self):
        found = NullOpeningHours().get_opening_hours(["a", "b"])
        assert found == {"a": None, "b": None}

    def test_start_hours_has_no_cells_so_all_places_become_checks(self):
        b = build()
        assert start_hours(b.trip, NullOpeningHours()) == {}

    def test_dev_llm_never_calls_a_model(self):
        llm = get_course_llm()
        assert llm == CourseLlm(goals_planner=None, direct_planner=None)


class TestRunWithoutRequest:
    def test_baseline_course_with_all_checks_and_no_model(self):
        b = build()
        out = run_course(b, "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        v = out.view
        assert out.model_turns == 0 and out.tokens_in == 0 and out.model is None
        assert v.outcome == "solved_with_checks" and v.goals == [] and v.unmatched == []
        assert [len(d["slots"]) for d in v.days] and sum(len(d["slots"]) for d in v.days) == 6
        assert len(v.checks) == 6 and all(s["needs_check"] for d in v.days for s in d["slots"])
        assert v.violations == []                              # 모름은 위반이 아니다
        assert v.steps[0]["stage"] == "이해" and v.steps[-1]["stage"] == "결과"

    def test_slots_are_pin_ids_in_order_and_legs_follow_the_order(self):
        out = run_course(build(), "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        for d in out.view.days:
            ids = [s["pin_id"] for s in d["slots"]]
            assert [s["order"] for s in d["slots"]] == list(range(1, len(ids) + 1))
            assert [(l["from_pin_id"], l["to_pin_id"]) for l in d["legs"]] == list(zip(ids, ids[1:]))
            assert all(l["approx_minutes"] >= 0 for l in d["legs"])
        assert {d["date"] for d in out.view.days} == {"2026-10-19", "2026-10-20", "2026-10-21"}

    def test_every_pin_appears_exactly_once(self):
        out = run_course(build(), "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        ids = sorted(s["pin_id"] for d in out.view.days for s in d["slots"])
        assert ids == sorted(f"pin-{i}" for i in range(1, 7))

    def test_live_pins_are_excluded_with_the_fixed_message_and_no_name(self):
        b = build(live=2)
        out = run_course(b, "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        assert out.view.excluded == [
            {"pin_id": "live-0", "reason": "NO_COORDINATES", "text": "좌표를 알 수 없어 동선에서 빠졌어요"},
            {"pin_id": "live-1", "reason": "NO_COORDINATES", "text": "좌표를 알 수 없어 동선에서 빠졌어요"},
        ]
        assert sum(len(d["slots"]) for d in out.view.days) == 6


class TestRunWithRequest:
    def test_stub_planners_set_goals_and_direct_the_course(self):
        direct = direct_planner()
        out = run_course(build(), TEXT, goals_planner=goals_planner, direct_planner=direct, gateway=NullOpeningHours())
        v = out.view
        assert [g["id"] for g in v.goals] == ["day_indoor:d2"] and v.goals[0]["label"] == "둘째 날 (화)은 실내 위주로"
        assert v.goals[0]["met"] in (True, False, None)
        assert v.unmatched == ["웨이팅 없는 곳으로"]
        assert out.model_turns == 2
        stages = [s["stage"] for s in v.steps]
        assert stages[0] == "이해" and "끝" in stages
        assert (v.steps[0]["role"], v.steps[0]["by"]) == ("해석", "ai") and "둘째 날 (화)은 실내 위주로" in v.steps[0]["text"]

    def test_goal_setting_failure_leaves_the_whole_request_unmatched(self):
        def failing(_input):
            raise LlmCallError("timeout", reason="timeout")

        out = run_course(build(), TEXT, goals_planner=failing, direct_planner=None, gateway=NullOpeningHours())
        assert out.view.goals == [] and out.view.unmatched == [TEXT]
        assert (out.view.steps[0]["by"], out.view.steps[0]["by_detail"]) == ("code", "코드(목표 세우기 실패)")   # 괄호 안에 괄호가 있어도 칸이 맞게 나뉜다
        assert out.view.outcome == "solved_with_checks"

    def test_without_a_goals_planner_the_request_is_unmatched(self):
        out = run_course(build(), TEXT, goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        assert out.view.goals == [] and out.view.unmatched == [TEXT]

    def test_model_input_never_has_names_or_coordinates(self):
        seen = []

        def spy(turn_input):
            seen.append(turn_input)
            return direct_planner()(turn_input) if len(seen) == 1 else CourseDirectTurn.model_validate(
                {"thought": "끝", "action": {"tool": "finish", "candidate_id": "c1"}})

        run_course(build(), TEXT, goals_planner=goals_planner, direct_planner=spy, gateway=NullOpeningHours())
        dumped = str(seen)
        assert seen and "장소1" not in dumped and "37.56" not in dumped and "own-1" not in dumped and "pin-1" not in dumped

    def test_member_walk_limit_becomes_violation_text_without_names_in_other_fields(self):
        far = [PinInput(f"pin-{i}", f"own-{i}", f"먼곳{i}", "관광지", 37.5 + i * 0.004, 127.0) for i in range(1, 4)]
        b = build_trip(far, (MON,), (core.MemberConstraint("daily_walk_max", 10),), unknown_hours="check")
        out = run_course(b, "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        assert any(v["kind"] == "member" and "구성원 조건 10분" in v["text"] for v in out.view.violations)
        assert out.view.outcome == "unresolved"


class TestViewTexts:
    def test_parse_steps_handles_roles_nested_parentheses_and_plain_lines(self):
        steps = parse_steps(["[이해] 해석(코드(목표 세우기 실패)) 이렇게 이해했어요: 없음", "[짜기] 지휘(모델 → 코드) 후보 c1",
                             "[답] 결정(코드) 기본값", "[질문] 지휘(코드가 열음 → 사람) 어느 날?", "그냥 줄"])
        assert steps == [
            {"stage": "이해", "role": "해석", "by": "code", "by_detail": "코드(목표 세우기 실패)", "text": "이렇게 이해했어요: 없음"},
            {"stage": "짜기", "role": "지휘", "by": "ai", "by_detail": "모델 → 코드", "text": "후보 c1"},
            {"stage": "답", "role": "결정", "by": "code", "by_detail": None, "text": "기본값"},
            {"stage": "질문", "role": "지휘", "by": "human", "by_detail": "코드가 열음 → 사람", "text": "어느 날?"},
            {"stage": "기록", "role": "지휘", "by": "code", "by_detail": None, "text": "그냥 줄"},
        ]

    def test_violation_texts(self):
        trip = build().trip
        closed = core.Violation("closed:p1:d1", "closed", "confirmed", "d1", ("p1",))
        leg = core.Violation("leg:p1-p2:d1", "travel", "confirmed", "d1", ("p1", "p2"), {"minutes": 45, "limit": 40})
        day = core.Violation("day:d1", "travel", "confirmed", "d1", ("p1", "p2", "p3"), {"minutes": 160, "limit": 150})
        member = core.Violation("member:d1", "member", "confirmed", "d1", ("p1",), {"minutes": 70, "limit": 60})
        assert violation_text(trip, closed) == "장소1은 첫째 날 (월)에 쉬는 날이에요"
        assert violation_text(trip, leg) == "첫째 날 (월) 장소1에서 장소2까지 걸어서 45분이에요(구간 상한 40분)"
        assert violation_text(trip, day) == "첫째 날 (월) 도보 합계 160분이에요(하루 상한 150분)"
        assert violation_text(trip, member) == "첫째 날 (월) 도보 70분이 구성원 조건 60분을 넘어요"

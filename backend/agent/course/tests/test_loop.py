"""에이전트 루프 — 도식 2 시나리오(명세 19절 1번), 기준선, 모델 실패 대행, 상한, 모델 입력의 비공개 정보."""

import json

import pytest
from pydantic import ValidationError

from agent.course import loop
from agent.course.constants import MAX_TURNS
from agent.course.schemas import AgentTurn
from agent.course.state import initial_state
from agent.course.tests.fixtures import COURSE, KNOWN_HOURS, PLACES, TRUE_HOURS, trip


def scripted(turns: list[dict]):
    """모델 자리에 넣는 스크립트. 받은 입력을 기록해 둔다."""
    seen: list[dict] = []
    queue = list(turns)

    def decide(turn_input: dict) -> AgentTurn:
        seen.append(turn_input)
        return AgentTurn.model_validate(queue.pop(0))

    decide.seen = seen
    return decide


def start():
    return initial_state(trip(), KNOWN_HOURS, COURSE)


DIAGRAM_2 = [
    {"thought": "{d2}에 영업 정보가 없는 곳이 둘이에요. 먼저 순서를 바꿔 볼게요",
     "action": {"tool": "try_move", "move": {"type": "swap", "a": "p4", "b": "p5"}}},
    {"thought": "바꿔도 그대로네요. {p5} 영업 정보부터 확인할게요", "lesson": "순서만 바꿔서는 결측이 안 풀린다",
     "action": {"tool": "get_opening_hours", "place": "p5"}},
    {"thought": "{p4} 영업 정보도 확인할게요", "action": {"tool": "get_opening_hours", "place": "p4"}},
    {"thought": "{p4}는 {d2}에 쉬네요. 문 여는 날을 찾아볼게요", "action": {"tool": "find_open_days", "place": "p4"}},
    {"thought": "{d3}로 옮겨 볼게요", "action": {"tool": "try_move", "move": {"type": "move_day", "place": "p4", "to_day": "d3"}}},
    {"thought": "위반이 없어졌어요. 채택할게요", "action": {"tool": "commit_move", "trial_id": "t2"}},
    {"thought": "식당도 연달아 있지 않아요. 마칠게요", "action": {"tool": "finish", "reason_code": "solved"}},
]


class TestDiagram2:
    """팀 공유 도식 2: 스왑 실패 → 조회로 결측 해소 → 휴무 확정 → 이월 → 종료."""

    def test_solves_in_seven_turns(self):
        result = loop.run_loop(start(), decide=scripted(DIAGRAM_2), hours=TRUE_HOURS)

        assert result.outcome == "solved"
        assert len(result.steps) == 7
        assert all(s.by == "model" and s.result.ok for s in result.steps)
        # 셋째 날은 이동이 같은 두 자리 중 앞자리에 넣는다 — 야경 명소 p6이 그대로 마지막에 남는다
        assert result.best_course == (("p1", "p2"), ("p3", "p5"), ("p4", "p6"))
        assert result.soft["night_last"] == 1.0

    def test_each_turn_moves_the_counts_like_the_diagram(self):
        steps = loop.run_loop(start(), decide=scripted(DIAGRAM_2), hours=TRUE_HOURS).steps

        swap, look_p5, look_p4, days, move, commit, _ = (s.result.data for s in steps)
        assert swap["hard_before"] == swap["hard_after"] == {"confirmed": 0, "unknown": 2}   # 스왑: 개선 없음
        assert look_p5["resolved_unknown"] == 1 and look_p5["hard"] == {"confirmed": 0, "unknown": 1}
        assert look_p4["hard"] == {"confirmed": 1, "unknown": 0}                            # 휴무 확정
        assert days == {"place": "p4", "open": ["d1", "d3"], "closed": ["d2"], "unknown": []}
        assert move["hard_after"] == {"confirmed": 0, "unknown": 0}
        assert commit["hard"] == {"confirmed": 0, "unknown": 0}

    def test_moving_the_restaurant_also_fixes_back_to_back_meals(self):
        result = loop.run_loop(start(), decide=scripted(DIAGRAM_2), hours=TRUE_HOURS)
        assert loop.core.soft_scores(result.state.trip, COURSE)["meal_spacing"] == 1
        assert result.soft["meal_spacing"] == 0

    def test_thoughts_are_rendered_with_names_and_lessons_kept(self):
        result = loop.run_loop(start(), decide=scripted(DIAGRAM_2), hours=TRUE_HOURS)
        assert result.steps[0].thought == "둘째 날 (화)에 영업 정보가 없는 곳이 둘이에요. 먼저 순서를 바꿔 볼게요"
        assert result.state.lessons == ("순서만 바꿔서는 결측이 안 풀린다",)


class TestBaseline:
    def test_baseline_alone_solves_the_same_map(self):
        result = loop.run_loop(start(), decide=None, hours=TRUE_HOURS)

        assert result.outcome == "solved"
        assert result.model_turns == 0
        tools_used = [s.call["tool"] for s in result.steps]
        assert tools_used == ["get_opening_hours", "get_opening_hours", "try_move", "commit_move", "finish"]

    def test_baseline_from_draft_course(self):
        # 초안 배치부터 시작해도 돈다
        result = loop.run_loop(initial_state(trip(), KNOWN_HOURS), decide=None, hours=TRUE_HOURS)
        assert result.outcome in ("solved", "solved_with_checks")


class TestModelFailures:
    def test_invalid_turns_are_covered_by_baseline_then_baseline_takes_over(self):
        calls = {"n": 0}

        def broken(_input):
            calls["n"] += 1
            return AgentTurn.model_validate({"thought": "x", "action": {"tool": "teleport"}})

        result = loop.run_loop(start(), decide=broken, hours=TRUE_HOURS)

        assert calls["n"] == 2                       # MAX_INVALID_TURNS 뒤로는 모델을 부르지 않는다
        assert result.model_turns == 0
        assert result.outcome == "solved"

    def test_code_bugs_are_not_swallowed(self):
        def buggy(_input):
            raise KeyError("버그")

        with pytest.raises(KeyError):
            loop.run_loop(start(), decide=buggy, hours=TRUE_HOURS)

    def test_bad_thought_is_hidden_but_action_still_runs(self):
        turns = [{"thought": "3번 시도해 볼게요", "action": {"tool": "get_opening_hours", "place": "p4"}},
                 {"thought": "마칠게요", "action": {"tool": "finish", "reason_code": "budget"}}]
        result = loop.run_loop(start(), decide=scripted(turns), hours=TRUE_HOURS)

        first = result.steps[0]
        assert first.thought is None and first.thought_problem == "슬롯 밖 숫자"
        assert first.result.ok


class TestLimits:
    def test_repeated_call_is_not_executed_again(self):
        same = {"thought": "다시 볼게요", "action": {"tool": "estimate_travel", "from_place": "p1", "to_place": "p2"}}
        result = loop.run_loop(start(), decide=scripted([same, same, {"thought": "끝", "action": {"tool": "finish", "reason_code": "budget"}}]),
                               hours=TRUE_HOURS)
        assert [s.repeated for s in result.steps] == [False, True, False]
        assert result.state.tool_counts["estimate_travel"] == 1

    def test_turn_cap_ends_with_best_state(self):
        def wander(turn_input):
            return AgentTurn.model_validate({"thought": "둘러볼게요", "action": {
                "tool": "estimate_travel", "from_place": "p1", "to_place": f"p{2 + turn_input['budget']['turns_left'] % 4}"}})

        result = loop.run_loop(start(), decide=wander, hours=TRUE_HOURS)
        assert len(result.steps) == MAX_TURNS
        assert result.outcome == "solved_with_checks"   # 아무것도 못 고쳤고 결측 2건이 남았다

    def test_timeout(self):
        ticks = iter([0.0, 1.0, 999.0])
        result = loop.run_loop(start(), decide=scripted(DIAGRAM_2), hours=TRUE_HOURS, clock=lambda: next(ticks))
        assert len(result.steps) == 1
        assert result.outcome == "solved_with_checks"


class TestTurnInputPrivacy:
    """모델 입력에는 별칭만 — pin_id, place_id, 좌표, 장소 이름이 없어야 한다(명세 3절 5번)."""

    def test_no_ids_coordinates_or_names(self):
        decide = scripted(DIAGRAM_2)
        loop.run_loop(start(), decide=decide, hours=TRUE_HOURS)

        dumped = json.dumps(decide.seen, ensure_ascii=False)
        for p in PLACES:
            assert p.pin_id not in dumped
            assert p.place_id not in dumped
            assert p.name not in dumped
            assert str(p.lat) not in dumped and str(p.lng) not in dumped

    def test_input_validates_against_schema_errors_as_model_failure(self):
        with pytest.raises(ValidationError):
            AgentTurn.model_validate({"thought": "x", "action": {"tool": "finish", "reason_code": "solved"}, "extra": 1})

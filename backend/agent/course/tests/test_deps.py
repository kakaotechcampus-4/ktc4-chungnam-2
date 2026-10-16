"""모델 자리(ModelDecider) — llm.api.agent_course_turn을 거쳐 루프에 붙는지, 실패가 기준선으로 넘어가는지."""

from agent.course import loop
from agent.course.deps import ModelDecider
from agent.course.schemas import AgentTurn
from agent.course.state import initial_state
from agent.course.tests.fixtures import COURSE, KNOWN_HOURS, TRUE_HOURS, trip
from agent.course.tests.test_loop import DIAGRAM_2
from llm.client import LlmCallError


def start():
    return initial_state(trip(), KNOWN_HOURS, COURSE)


def test_planner_turns_drive_the_loop():
    queue = [AgentTurn.model_validate(t) for t in DIAGRAM_2]
    seen = []

    def planner(turn_input):
        seen.append(turn_input["turn"])
        return queue.pop(0)

    decider = ModelDecider(planner)
    result = loop.run_loop(start(), decide=decider, hours=TRUE_HOURS)

    assert result.outcome == "solved" and result.model_turns == 7
    assert seen == [1, 2, 3, 4, 5, 6, 7]
    assert len(decider.usages) == 7 and decider.failures == []


def test_failed_model_turns_fall_back_to_baseline():
    def planner(_):
        raise LlmCallError("timeout", reason="timeout")

    decider = ModelDecider(planner)
    result = loop.run_loop(start(), decide=decider, hours=TRUE_HOURS)

    assert result.outcome == "solved"
    assert result.model_turns == 0 and result.baseline_turns == len(result.steps)
    assert [f.reason for f in decider.failures] == ["timeout", "timeout"]   # 두 번 실패한 뒤 모델을 더 부르지 않는다

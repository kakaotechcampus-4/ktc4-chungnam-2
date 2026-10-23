"""동선 에이전트의 모델 자리(decide)를 llm 공개 함수로 채운다(recommend/deps.py, agent/deps.py와 같은 자리).

`llm.api.agent_course_turn`은 실패를 AgentCallFailed로 돌려준다. 루프는 예외로 실패를 알아채고 그 턴을 기준선에 넘기므로
여기서 예외(ModelTurnFailed)로 바꾼다. 사용량(AgentUsage)은 턴마다 모아 둔다 — M1에서 agent_course_runs의 model,
prompt_version, tokens_in, tokens_out에 채운다.
"""

from __future__ import annotations

from typing import Any, Mapping

from llm.api import (
    AgentCallFailed, AgentUsage, CourseTurn, CourseTurnPlanner, agent_course_turn, course_direct_turn, course_set_goals,
)


class ModelTurnFailed(RuntimeError):
    """모델 턴이 실패했다(호출 실패, 타임아웃, 스키마 검증 실패). loop.MODEL_FAILURES에 든다(RuntimeError)."""

    def __init__(self, failure: AgentCallFailed):
        super().__init__(f"{failure.reason}: {failure.detail}")
        self.failure = failure


class ModelDecider:
    """loop.run_loop(decide=...)에 넣는 모델 자리. planner로 실제 모델(real_course_turn_planner)이나 테스트 대역을 받는다."""

    def __init__(self, planner: CourseTurnPlanner):
        self._planner = planner
        self.usages: list[AgentUsage] = []
        self.failures: list[AgentCallFailed] = []

    def __call__(self, turn_input: Mapping[str, Any]) -> CourseTurn:
        reply = agent_course_turn(turn_input, planner=self._planner)
        self.usages.append(reply.usage)
        if isinstance(reply.result, AgentCallFailed):
            self.failures.append(reply.result)
            raise ModelTurnFailed(reply.result)
        return reply.result

    @property
    def tokens(self) -> tuple[int, int]:
        return sum(u.tokens_in for u in self.usages), sum(u.tokens_out for u in self.usages)


class _Metered:
    """llm 호출 결과(AgentReply)를 받아 사용량을 모으고 실패를 ModelTurnFailed로 바꾸는 공통 부분."""

    def __init__(self) -> None:
        self.usages: list[AgentUsage] = []
        self.failures: list[AgentCallFailed] = []

    def _unwrap(self, reply):
        self.usages.append(reply.usage)
        if isinstance(reply.result, AgentCallFailed):
            self.failures.append(reply.result)
            raise ModelTurnFailed(reply.result)
        return reply.result

    @property
    def tokens(self) -> tuple[int, int]:
        return sum(u.tokens_in for u in self.usages), sum(u.tokens_out for u in self.usages)

    @property
    def calls(self) -> int:
        return len(self.usages)


class GoalSetter(_Metered):
    """요청 한 줄 → CourseGoalSet. planner로 실제 모델(real_course_goals_planner)이나 스텁(fixed_course_goals_planner)을 받는다."""

    def __init__(self, planner):
        super().__init__()
        self._planner = planner

    def __call__(self, goals_input):
        return self._unwrap(course_set_goals(goals_input, planner=self._planner))


class DirectDecider(_Metered):
    """지휘 턴의 모델 자리(direct.run_direct(decide=...))."""

    def __init__(self, planner):
        super().__init__()
        self._planner = planner

    def __call__(self, turn_input):
        return self._unwrap(course_direct_turn(turn_input, planner=self._planner))

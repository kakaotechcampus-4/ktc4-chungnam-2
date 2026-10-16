"""동선 에이전트의 모델 자리(decide)를 llm 공개 함수로 채운다(recommend/deps.py, agent/deps.py와 같은 자리).

`llm.api.agent_course_turn`은 실패를 AgentCallFailed로 돌려준다. 루프는 예외로 실패를 알아채고 그 턴을 기준선에 넘기므로
여기서 예외(ModelTurnFailed)로 바꾼다. 사용량(AgentUsage)은 턴마다 모아 둔다 — M1에서 agent_course_runs의 model,
prompt_version, tokens_in, tokens_out에 채운다.
"""

from __future__ import annotations

from typing import Any, Mapping

from llm.api import AgentCallFailed, AgentUsage, CourseTurn, CourseTurnPlanner, agent_course_turn


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

"""v2 동선 에이전트 턴(agent_course_turn, #334) — 출력 스키마, 실제 호출 경로(클라이언트 대역), 실패 처리.

원칙: 실패는 재요청하지 않고 AgentCallFailed로 돌려준다(그 턴은 agent의 기준선이 대신한다). 엘리스 strict 구조화 출력은
oneOf를 거절하므로 출력 스키마에 oneOf가 없어야 한다.
"""

import json
from functools import partial
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from llm import api as llm_api
from llm import client as llm_client
from llm import service
from llm.client import LlmCallError
from llm.prompts import COURSE_TURN_PROMPT, COURSE_TURN_PROMPT_VERSION
from llm.schemas import AgentCallFailed, CourseTryMove, CourseTurn

TURN_INPUT = {"turn": 3, "days": [{"day": "d1", "places": [{"place": "p1", "category": "음식점", "labels": []}]}],
              "violations": [], "budget": {"turns_left": 14}}

TRY = {"thought": "{p1}을 {d2}로 옮겨 볼게요", "plan": [{"step": 1, "intent": "옮겨 보기"}], "lesson": None,
       "action": {"tool": "try_move", "move": {"type": "move_day", "place": "p1", "to_day": "d2", "position": None}}}


class TestSchema:
    def test_strict_schema_has_no_oneof(self):
        dumped = json.dumps(to_strict_json_schema(CourseTurn))
        assert "oneOf" not in dumped
        assert "anyOf" in dumped   # 도구·수리 Union은 anyOf로 나간다

    def test_union_resolves_without_discriminator(self):
        turn = CourseTurn.model_validate(TRY)
        assert isinstance(turn.action, CourseTryMove)
        assert turn.action.move.type == "move_day"

    @pytest.mark.parametrize("bad", [
        {**TRY, "action": {"tool": "teleport"}},                                     # 없는 도구
        {**TRY, "action": {"tool": "finish", "reason_code": "solved", "x": 1}},      # 스키마 밖 칸
        {**TRY, "extra": 1},
    ])
    def test_rejects_out_of_schema(self, bad):
        with pytest.raises(ValueError):
            CourseTurn.model_validate(bad)


def _completion(parsed):
    message = SimpleNamespace(parsed=parsed, tool_calls=None, content=None, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=300, completion_tokens=40))


class FakeClient:
    def __init__(self, step):
        self.kwargs = None
        self._step = step
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self._step, BaseException):
            raise self._step
        return _completion(self._step)


class TestRealPlannerPath:
    def test_success_returns_turn_and_usage(self):
        client = FakeClient(CourseTurn.model_validate(TRY))
        reply = service.agent_course_turn(TURN_INPUT, planner=partial(llm_client.call_course_turn, client, turn=3))

        assert isinstance(reply.result, CourseTurn)
        assert (reply.usage.prompt_version, reply.usage.tokens_in, reply.usage.tokens_out) == (COURSE_TURN_PROMPT_VERSION, 300, 40)

    def test_request_shape(self):
        client = FakeClient(CourseTurn.model_validate(TRY))
        service.agent_course_turn(TURN_INPUT, planner=partial(llm_client.call_course_turn, client, turn=3))

        kw = client.kwargs
        assert kw["response_format"] is CourseTurn
        assert "tools" not in kw and "reasoning_effort" not in kw     # 도구를 tools로 주지 않는다
        assert kw["messages"][0] == {"role": "system", "content": COURSE_TURN_PROMPT}
        assert json.loads(kw["messages"][1]["content"]) == TURN_INPUT  # 입력은 JSON 문자열로만

    def test_call_failure_becomes_result_not_exception(self):
        client = FakeClient(RuntimeError("network"))
        reply = service.agent_course_turn(TURN_INPUT, planner=partial(llm_client.call_course_turn, client, turn=3))
        assert isinstance(reply.result, AgentCallFailed) and reply.result.reason == "call_failed"

    def test_empty_parsed_is_invalid_schema(self):
        client = FakeClient(None)
        reply = service.agent_course_turn(TURN_INPUT, planner=partial(llm_client.call_course_turn, client, turn=3))
        assert isinstance(reply.result, AgentCallFailed) and reply.result.reason == "invalid_schema"

    def test_planner_value_error_is_invalid_schema(self):
        def planner(_):
            raise ValueError("깨진 응답")
        reply = service.agent_course_turn(TURN_INPUT, planner=planner)
        assert reply.result.reason == "invalid_schema"

    def test_unexpected_planner_bug_is_not_swallowed(self):
        def planner(_):
            raise KeyError("버그")
        with pytest.raises(KeyError):
            service.agent_course_turn(TURN_INPUT, planner=planner)

    def test_llm_call_error_reason_is_kept(self):
        def planner(_):
            raise LlmCallError("timeout", reason="timeout")
        assert service.agent_course_turn(TURN_INPUT, planner=planner).result.reason == "timeout"


def test_public_api():
    assert llm_api.agent_course_turn is service.agent_course_turn
    assert llm_api.real_course_turn_planner is service.real_course_turn_planner


def test_프롬프트_v2는_checks_입력을_설명한다():
    assert COURSE_TURN_PROMPT_VERSION == "course-turn-v6"
    assert "checks" in COURSE_TURN_PROMPT and "확인 필요" in COURSE_TURN_PROMPT


def test_프롬프트_v4는_새_soft_키와_다듬기_우선_규칙을_담는다():
    for word in ("mono_category_days", "no_tour_days", "cafe_spacing", "open_days", "closed_days", "turns_left", "확정 위반(hard.confirmed)이 0이면"):
        assert word in COURSE_TURN_PROMPT

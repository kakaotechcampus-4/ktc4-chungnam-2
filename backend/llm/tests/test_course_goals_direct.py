"""동선 목표 세우기(course_set_goals)와 지휘 턴(course_direct_turn) — 스키마, 요청 모양, 스텁, 실패 처리(#334)."""

import json
from functools import partial
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from llm import api as llm_api
from llm import client as llm_client
from llm import service
from llm.prompts import (
    COURSE_DIRECT_PROMPT, COURSE_DIRECT_PROMPT_VERSION, COURSE_GOALS_PROMPT, COURSE_GOALS_PROMPT_VERSION,
)
from llm.schemas import AgentCallFailed, CourseDirectTurn, CourseGoalSet

GOALS_INPUT = {"request": "첫날 저녁엔 야경 보고 싶어요", "days": [{"day": "d1", "weekday": "월요일"}], "first_day": "d1",
               "last_day": "d1", "places": [{"place": "p1", "name": "남산타워", "category": "관광지"}]}
GOAL_SET = {"goals": [{"kind": "night_end", "day": "d1", "places": [], "source": "request", "quote": "첫날 저녁엔 야경", "reaction_ids": []}],
            "unmatched": []}
DIRECT_INPUT = {"turn": 1, "goals": [], "candidates": [], "budget": {"turns_left": 5}}
DIRECT_TURN = {"thought": "후보를 짜 볼게요", "action": {"tool": "optimize", "priority": ["night_end:d1"], "locks": []}}


class TestSchemas:
    @pytest.mark.parametrize("model", [CourseGoalSet, CourseDirectTurn])
    def test_strict_schema_has_no_oneof(self, model):
        assert "oneOf" not in json.dumps(to_strict_json_schema(model))

    def test_union_resolves_without_discriminator(self):
        turn = CourseDirectTurn.model_validate(DIRECT_TURN)
        assert turn.action.tool == "optimize" and turn.action.priority == ["night_end:d1"]
        assert CourseDirectTurn.model_validate({"thought": "x", "action": {"tool": "finish", "candidate_id": "c1"}}).action.candidate_id == "c1"

    @pytest.mark.parametrize("bad", [
        {"thought": "x", "action": {"tool": "try_move"}},                                            # 옛 도구는 지휘 턴에 없다
        {"thought": "x", "action": {"tool": "finish", "candidate_id": "c1", "reason_code": "solved"}},
        {"thought": "x", "action": {"tool": "ask_requester", "kind": "keep_or_review"}},             # 이번 범위의 질문 종류가 아니다
    ])
    def test_rejects_out_of_scope(self, bad):
        with pytest.raises(ValueError):
            CourseDirectTurn.model_validate(bad)

    def test_goal_kind_is_limited_to_six(self):
        with pytest.raises(ValueError):
            CourseGoalSet.model_validate({"goals": [{**GOAL_SET["goals"][0], "kind": "romantic"}], "unmatched": []})


def _completion(parsed):
    message = SimpleNamespace(parsed=parsed, tool_calls=None, content=None, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=200, completion_tokens=30))


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


class TestGoals:
    def test_success_and_request_shape(self):
        client = FakeClient(CourseGoalSet.model_validate(GOAL_SET))
        reply = service.course_set_goals(GOALS_INPUT, planner=partial(llm_client.call_course_goals, client))
        assert isinstance(reply.result, CourseGoalSet) and reply.result.goals[0].kind == "night_end"
        assert (reply.usage.prompt_version, reply.usage.tokens_in, reply.usage.tokens_out) == (COURSE_GOALS_PROMPT_VERSION, 200, 30)
        kw = client.kwargs
        assert kw["response_format"] is CourseGoalSet and "tools" not in kw
        assert kw["messages"][0] == {"role": "system", "content": COURSE_GOALS_PROMPT}
        assert json.loads(kw["messages"][1]["content"]) == GOALS_INPUT

    def test_failures_become_results_not_exceptions(self):
        reply = service.course_set_goals(GOALS_INPUT, planner=partial(llm_client.call_course_goals, FakeClient(RuntimeError("net"))))
        assert isinstance(reply.result, AgentCallFailed) and reply.result.reason == "call_failed"
        reply = service.course_set_goals(GOALS_INPUT, planner=partial(llm_client.call_course_goals, FakeClient(None)))
        assert reply.result.reason == "invalid_schema"

    def test_stub_makes_no_goals_and_sends_the_whole_request_to_unmatched(self):
        reply = service.course_set_goals(GOALS_INPUT, planner=service.fixed_course_goals_planner)
        assert reply.result.goals == [] and reply.result.unmatched == [GOALS_INPUT["request"]]

    def test_prompt_lists_all_kinds_and_forbids_inventing(self):
        for kind in ("day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together", "unmatched", "그대로"):
            assert kind in COURSE_GOALS_PROMPT
        assert COURSE_GOALS_PROMPT_VERSION == "course-goals-v1"


class TestDirect:
    def test_success_and_request_shape(self):
        client = FakeClient(CourseDirectTurn.model_validate(DIRECT_TURN))
        reply = service.course_direct_turn(DIRECT_INPUT, planner=partial(llm_client.call_course_direct, client, turn=1))
        assert isinstance(reply.result, CourseDirectTurn) and reply.usage.prompt_version == COURSE_DIRECT_PROMPT_VERSION
        kw = client.kwargs
        assert kw["response_format"] is CourseDirectTurn and "tools" not in kw and "reasoning_effort" not in kw
        assert kw["messages"][0] == {"role": "system", "content": COURSE_DIRECT_PROMPT}
        assert json.loads(kw["messages"][1]["content"]) == DIRECT_INPUT

    def test_failure_becomes_result(self):
        reply = service.course_direct_turn(
            DIRECT_INPUT, planner=partial(llm_client.call_course_direct, FakeClient(RuntimeError("net")), turn=1))
        assert isinstance(reply.result, AgentCallFailed)

    def test_prompt_describes_the_four_tools_and_the_rules(self):
        for word in ("optimize", "lock", "ask_requester", "finish", "pick_course", "ask_closed_day", "met", "turns_left"):
            assert word in COURSE_DIRECT_PROMPT
        assert COURSE_DIRECT_PROMPT_VERSION == "course-direct-v2"
        assert "pick_course" in COURSE_DIRECT_PROMPT and "두 번 넘게" in COURSE_DIRECT_PROMPT and "묻지 않는다" in COURSE_DIRECT_PROMPT


def test_public_api():
    assert llm_api.course_set_goals is service.course_set_goals
    assert llm_api.course_direct_turn is service.course_direct_turn
    assert llm_api.fixed_course_goals_planner is service.fixed_course_goals_planner

"""지도 현황 문단 호출(agent_status, #1168, docs/agent-v2.md 8.2) — 요청 모양, 실패 처리, 고정 응답 스텁, 사용량 기록.

원칙: 입력은 agent가 센 칸뿐이고 JSON 문자열로만 넘긴다. 도구 없이 구조화 출력(StatusOutput), reasoning_effort=none. 실패는
재요청하지 않고 AgentCallFailed로 돌려준다(2절 10번). 상태가 사실과 맞는지는 agent의 core.verify_status가 본다.
"""

import json
from functools import partial
from types import SimpleNamespace

import httpx
import openai
import pytest

from llm import api as llm_api
from llm import service, usage
from llm.client import call_agent_status
from llm.prompts import AGENT_STATUS_PROMPT, AGENT_STATUS_PROMPT_VERSION
from llm.schemas import AgentCallFailed, StatusOutput

CELLS = {
    "dday": 5, "first_category": "음식점", "first_reason": "의견이 갈린 핀이 있다",
    "categories": [
        {"category": "음식점", "confirmed": 0, "pins": 2, "split_pins": 1, "stalled": False, "unreacted_pins": 1},
        {"category": "카페", "confirmed": 1, "pins": 1, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
        {"category": "관광지", "confirmed": 0, "pins": 0, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
    ],
}
OUT = StatusOutput.model_validate({
    "categories": [{"category": "음식점", "state": "split_left"}, {"category": "카페", "state": "almost"},
                   {"category": "관광지", "state": "empty"}],
    "paragraph": "카페는 거의 정해졌고, 음식점은 갈린 곳 하나만 남았어요. 관광지는 아직 후보가 없어요. 출발이 5일 남았으니 음식점부터 보면 좋겠어요.",
})


class FakeClient:
    def __init__(self, *steps):
        self.calls = []
        self._steps = list(steps)
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        message = SimpleNamespace(parsed=step, tool_calls=None, content=None, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=900, completion_tokens=80))


def _status(client):
    return service.agent_status(CELLS, planner=partial(call_agent_status, client))


def test_api_opens_status_functions():
    assert llm_api.agent_status is service.agent_status
    for name in ("fixed_status_planner", "real_status_planner", "StatusOutput"):
        assert getattr(llm_api, name) is not None


def test_request_is_structured_output_without_tools_and_reasoning_none():
    client = FakeClient(OUT)

    reply = _status(client)

    assert reply.result == OUT
    [call] = client.calls
    assert call["reasoning_effort"] == "none" and call["response_format"] is StatusOutput
    assert "tools" not in call and "tool_choice" not in call
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][0]["content"] == AGENT_STATUS_PROMPT
    assert json.loads(call["messages"][1]["content"]) == CELLS   # 입력은 칸 그대로, JSON 문자열로만
    assert (reply.usage.prompt_version, reply.usage.tokens_in, reply.usage.tokens_out) == (
        AGENT_STATUS_PROMPT_VERSION, 900, 80)


@pytest.mark.parametrize("error, reason", [
    (openai.APITimeoutError(request=httpx.Request("POST", "http://x")), "timeout"),
    (openai.APIConnectionError(request=httpx.Request("POST", "http://x")), "call_failed"),
    (ValueError("깨진 JSON"), "invalid_schema"),
])
def test_failure_is_returned_not_raised_and_not_retried(error, reason):
    client = FakeClient(error)

    reply = _status(client)

    assert isinstance(reply.result, AgentCallFailed) and reply.result.reason == reason
    assert len(client.calls) == 1   # 다시 묻지 않는다


def test_empty_parsed_is_invalid_schema():
    reply = _status(FakeClient(None))
    assert isinstance(reply.result, AgentCallFailed) and reply.result.reason == "invalid_schema"


def test_fixed_stub_never_contradicts_cells_and_has_no_numbers():
    """dev 스텁 — 상태는 칸과 어긋나지 않는 쪽, 문단은 숫자 없는 고정 문구, 먼저 볼 카테고리만 권한다."""
    cells = {**CELLS, "categories": CELLS["categories"] + [
        {"category": "숙소", "confirmed": 0, "pins": 1, "split_pins": 0, "stalled": True, "unreacted_pins": 1}]}

    reply = service.agent_status(cells, planner=service.fixed_status_planner)

    assert [(c.category, c.state) for c in reply.result.categories] == [
        ("음식점", "split_left"), ("카페", "almost"), ("관광지", "empty"), ("숙소", "stalled")]
    assert reply.result.paragraph == "지도 현황을 정리했어요. 음식점부터 보면 좋겠어요."
    assert reply.usage.model is None   # 모델을 부르지 않았다
    no_first = service.agent_status({**CELLS, "first_category": None}, planner=service.fixed_status_planner)
    assert no_first.result.paragraph == "지도 현황을 정리했어요."


def test_usage_row_is_labelled_agent_status(llm_usage_rows):
    with llm_api.usage_context("agent_status", map_id="m1"):
        _status(FakeClient(OUT))

    [row] = llm_usage_rows
    assert (row["feature"], row["call"], row["map_id"], row["user_id"]) == ("agent_status", "agent_status", "m1", None)
    assert row["prompt_version"] == AGENT_STATUS_PROMPT_VERSION and row["ok"] is True


def test_prompt_names_every_state_and_the_rules():
    """지시문에 상태 일곱 가지와 말투 예시, #1152 예시 문장, 숫자·먼저 볼 카테고리 규칙이 있다."""
    from typing import get_args
    from llm.schemas import StatusState

    for state in get_args(StatusState):
        assert f"- {state}(" in AGENT_STATUS_PROMPT
    assert "출발이 5일 남았으니 음식점부터 보면 좋겠어요" in AGENT_STATUS_PROMPT
    assert "입력 칸에 있는 값만" in AGENT_STATUS_PROMPT and "first_category" in AGENT_STATUS_PROMPT
    assert usage.current_label() is None

"""같은 JSON 두 번(#767 3번 b) — 모델이 같은 JSON 객체를 두 번 이어 내면 첫 객체를 같은 스키마로 검증해 받는다.

받는 곳은 출구 client._agent_parse 하나다. 반복이 아니거나(다른 객체, 객체 + 쓰레기) 첫 객체가 스키마에 맞지 않으면 지금처럼
실패다. 다시 묻지 않는다(명세 2절 10번). 받았으면 llm_calls.outcome이 ok_repeated_json이고, 응답 원문은 로그에 남지 않는다(#390).
"""

import json
import logging
from functools import partial
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from llm import client as llm_client
from llm import service, usage
from llm.schemas import AgentCallFailed, DiagnosisOutput

STALL = {"signal_id": "s2", "diagnosis": "stall", "category": "음식점"}
MARK = "반복표지-원문은-로그에-남지-않는다"


def _silent(signal_id="s2"):
    return DiagnosisOutput(decision="silent", diagnosis="stall", signal_id=signal_id, claims=[], advice=[], actions=[])


def _json(output: DiagnosisOutput) -> str:
    return output.model_dump_json()


def _parse_error(raw: str) -> ValidationError:
    """SDK의 parse가 내는 것과 같은 오류 — 응답 content를 response_format.model_validate_json으로 읽다 난 json_invalid."""
    try:
        DiagnosisOutput.model_validate_json(raw)
    except ValidationError as err:
        return err
    raise AssertionError("ValidationError가 나야 한다")


class FakeClient:
    def __init__(self, raw: str):
        self.calls = 0
        self._raw = raw
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls += 1
        raise _parse_error(self._raw)


def _diagnose(raw: str):
    client = FakeClient(raw)
    reply = service.agent_diagnose(
        STALL, tool_runner=lambda *a: {"ok": True}, planner=partial(service._model_diagnosis_planner, client),
    )
    return reply.result, client


class TestReadJsonRepeat:
    def test_same_object_twice(self):
        shape = llm_client.read_json_repeat('  {"a": 1}\n{"a": 1}  ')
        assert shape.repeated and shape.first == {"a": 1} and shape.first_end == 8

    def test_different_object_twice(self):
        assert not llm_client.read_json_repeat('{"a": 1}{"a": 2}').repeated

    def test_object_and_garbage(self):
        assert not llm_client.read_json_repeat('{"a": 1}{"a": 1').repeated
        assert not llm_client.read_json_repeat('{"a": 1} 끝').repeated

    def test_three_times_is_not_a_repeat(self):
        assert not llm_client.read_json_repeat('{"a": 1}{"a": 1}{"a": 1}').repeated

    def test_unreadable(self):
        assert llm_client.read_json_repeat("not json") == llm_client.JsonRepeat(None, None, False)

    def test_single_object_is_not_a_repeat(self):
        assert not llm_client.read_json_repeat('{"a": 1}').repeated


class TestAgentParse:
    def test_same_object_twice_is_accepted(self, llm_usage_rows):
        with usage.usage_context("agent_diagnose", map_id="m1"):
            out, client = _diagnose(_json(_silent()) + "\n" + _json(_silent()))

        assert out == _silent()
        assert client.calls == 1   # 다시 묻지 않는다
        [row] = llm_usage_rows
        assert (row["outcome"], row["ok"]) == (llm_client.REPEATED_JSON_OUTCOME, True)

    def test_different_objects_fail(self, llm_usage_rows):
        with usage.usage_context("agent_diagnose", map_id="m1"):
            out, client = _diagnose(_json(_silent()) + _json(_silent("s9")))

        assert isinstance(out, AgentCallFailed) and out.reason == "invalid_schema"
        assert client.calls == 1
        [row] = llm_usage_rows
        assert (row["outcome"], row["ok"]) == ("invalid_schema", False)

    def test_object_and_garbage_fail(self):
        out, _ = _diagnose(_json(_silent()) + '{"decision": "sil')
        assert isinstance(out, AgentCallFailed) and out.reason == "invalid_schema"

    def test_repeated_object_that_breaks_the_schema_fails(self):
        bad = json.dumps({"decision": "maybe"})
        out, _ = _diagnose(bad + bad)
        assert isinstance(out, AgentCallFailed) and out.reason == "invalid_schema"

    def test_normal_response_is_unchanged(self, llm_usage_rows):
        parsed = _silent()
        message = SimpleNamespace(parsed=parsed, tool_calls=None, content=_json(parsed), refusal=None)
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: completion)))
        with usage.usage_context("agent_diagnose", map_id="m1"):
            reply = service.agent_diagnose(
                STALL, tool_runner=lambda *a: {"ok": True}, planner=partial(service._model_diagnosis_planner, client),
            )

        assert reply.result == parsed
        [row] = llm_usage_rows
        assert (row["outcome"], row["input_tokens"]) == ("ok", 10)

    def test_raw_response_is_not_logged(self, caplog):
        output = _silent(signal_id=MARK)
        caplog.set_level(logging.DEBUG, logger="pingo.llm")
        _diagnose(_json(output) + _json(output))
        _diagnose(_json(output) + _json(_silent()))

        assert caplog.records
        assert all(MARK not in r.getMessage() for r in caplog.records)

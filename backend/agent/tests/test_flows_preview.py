"""관찰 흐름의 미리 돌려 보기(명세 6.7, #1180) — 진단 전에 코드가 recommend.api.preview_filter를 부르고, 결과를 진단 입력과
도구 기록 p1에 넣고, 수가 0이면 「추천 받기」를 뺀다. ②가 실패하면 미리 돌려 보기와 그 검사를 건너뛴다.

recommend의 거르기 자체는 recommend/tests/test_preview_filter.py가 본다. 여기서는 대부분 recommend.api.preview_filter를 대역으로
바꿔 수를 정해 두고 agent의 흐름을 본다. 대역 없이 실제 함수를 거치는 경우도 하나 둔다."""

import json

import pytest

from agent import flows, tools
from agent.models import AgentRun, AgentSuggestion
from agent.schemas import DiagnosisOutput
from agent.tests.test_flows_model import (
    AGAINST_TEXT, LIKE_TEXT, FakeGateway, _split_map, _stall_map, good_stall, observe,
)
from agent.tests.world import World, fake_places, real_now
from llm import api as llm_api
from places import api as places_api
from recommend import api as recommend_api

FUNNEL = [{"key": "pool", "removed_count": 0}, {"key": "radius", "removed_count": 3},
          {"key": "closed", "removed_count": 0}, {"key": "disqualify", "removed_count": 2}]


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


@pytest.fixture()
def previews(monkeypatch):
    """recommend.api.preview_filter 대역. 받은 인자를 남기고 정해 둔 수를 돌려준다(passed, with_keys)."""
    calls: list[dict] = []
    counts = {"passed": 4, "with_keys": 1}

    def fake(db, *, map_id, category, text_lines, with_keys=(), **_):
        calls.append({"map_id": map_id, "category": category, "text_lines": text_lines, "with_keys": list(with_keys)})
        return {"passed_count": counts["passed"], "with_keys_count": counts["with_keys"] if with_keys else None,
                "funnel": FUNNEL}

    monkeypatch.setattr(recommend_api, "preview_filter", fake)
    return calls, counts


def stall_with_count(inp, call_tool):
    """미리 돌려 본 수를 p1로 가리키고 「추천 받기」와 「핀 보기」를 고른다."""
    ready = call_tool("get_readiness", {"category": inp["category"]})
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "stall", "signal_id": inp["signal_id"],
        "claims": [
            {"id": "c1", "kind": "tool_result", "call_id": ready["call_id"], "path": "ready", "value": True},
            {"id": "c2", "kind": "tool_result", "call_id": "p1", "path": "passed_count",
             "value": inp["preview"]["passed_count"]},
            {"id": "c3", "kind": "ref", "object": "pin", "ref_id": inp["against_pin_ids"][0]},
        ],
        "advice": [{"text": "지금 조건으로 찾으면 맞는 곳이 {c2.value}곳 있어요", "basis": ["c2"], "is_guess": False}],
        "actions": [
            {"type": "open_recommend", "category": None, "pin_ids": None, "basis": ["c1", "c2"]},
            {"type": "show_pins", "category": None, "pin_ids": inp["against_pin_ids"], "basis": ["c3"]},
        ],
    })


def test_stall_preview_goes_into_the_input_and_the_tool_log_as_p1(world, previews):
    calls, _ = previews
    map_id, _, against = _stall_map(world)
    gateway = FakeGateway(diagnose=stall_with_count)

    assert observe(world, map_id, gateway) == "suggested"

    [inp] = gateway.inputs
    assert inp["preview"] == {"passed_count": 4}   # 깔때기와 장소는 모델에 가지 않는다
    [call] = calls
    assert (call["category"], call["with_keys"]) == ("음식점", [])
    assert set(call["text_lines"]) == {against}   # 그 카테고리 사유 있는 반응 전부의 ② 결과
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    preview, readiness = run.tool_calls
    assert (preview["call_id"], preview["name"], preview["args"]) == ("p1", "preview_filter", {"category": "음식점", "with_keys": []})
    assert preview["result"] == {"passed_count": 4, "funnel": FUNNEL}
    assert readiness["call_id"] == "t1"   # 모델이 고른 도구 번호는 그대로 t1부터(미리 돌려 보기는 상한에 세지 않는다)
    sug = world.one(AgentSuggestion, map_id=map_id)
    assert [a["type"] for a in sug.actions] == ["open_recommend", "show_pins"]
    assert {"id": "c2", "kind": "tool_result", "call_id": "p1", "path": "passed_count", "value": 4} in sug.claims


def test_zero_places_drop_the_recommend_button_but_keep_the_rest(world, previews):
    _, counts = previews
    counts["passed"] = 0
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, FakeGateway(diagnose=stall_with_count)) == "suggested"

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert [a["type"] for a in sug.actions] == ["show_pins"]
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.verification["actions"]["removed"] == [{"index": 0, "reason": "preview_empty"}]


def test_structuring_failure_skips_the_preview_and_its_check(world, previews):
    calls, _ = previews
    map_id, _, _ = _stall_map(world)

    class Failing(FakeGateway):
        def structure(self, raw):
            raise llm_api.PlanEvidenceFailed("timeout")

    gateway = Failing(diagnose=good_stall)
    assert observe(world, map_id, gateway) == "suggested"

    assert calls == [] and gateway.inputs[0]["preview"] is None
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert [c["name"] for c in run.tool_calls] == ["get_readiness"]   # p1이 없다
    assert [a["type"] for a in world.one(AgentSuggestion, map_id=map_id).actions] == ["open_recommend"]


class Keyed(FakeGateway):
    """② 대역 — ♥ 글은 조용한 곳 원함, 🚫 글은 주차 원함(서로 다른 특징, different_axes)."""
    KEYS = {LIKE_TEXT: ("quiet", True), AGAINST_TEXT: ("parking_available", True)}

    def structure(self, raw):
        return [[llm_api.EvidenceLine(source="reaction", text=r["text"], badge=r["badge"], fact_key=self.KEYS[r["text"]][0],
                                      wants=self.KEYS[r["text"]][1])] for r in raw]


def split_with_compromise(inp, call_tool):
    pin = inp["pin_id"]
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "split", "signal_id": inp["signal_id"],
        "claims": [
            {"id": "c1", "kind": "count", "subject": "pin", "subject_id": pin, "metric": "like", "value": 2},
            {"id": "c2", "kind": "count", "subject": "pin", "subject_id": pin, "metric": "against", "value": 1},
            {"id": "c3", "kind": "tool_result", "call_id": "p1", "path": "with_keys_count",
             "value": inp["preview"]["with_keys_count"]},
        ],
        "advice": [{"text": "두 의견을 다 맞추는 곳이 {c3.value}곳 있어요", "basis": ["c3"], "is_guess": False}],
        "actions": [{"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c1", "c2"]}],
    })


def test_split_on_different_axes_counts_places_that_satisfy_both_sides(world, previews):
    calls, _ = previews
    map_id, pin_id, like, against = _split_map(world)
    gateway = Keyed(diagnose=split_with_compromise)

    assert observe(world, map_id, gateway) == "suggested"

    [inp] = gateway.inputs
    assert inp["comparison"]["conflict_type"] == "different_axes"
    label = recommend_api.fact_labels()["quiet"]
    assert inp["preview"] == {"passed_count": 4, "with_keys_count": 1, "with_labels": [label]}
    [call] = calls
    assert call["with_keys"] == ["quiet"]   # ♥ 쪽이 원한 키. 🚫 쪽 주차는 근거 줄로 이미 들어간다
    assert call["text_lines"][like] == [{"fact_key": "quiet", "wants": True, "badge": "preferred"}]
    assert call["text_lines"][against] == [{"fact_key": "parking_available", "wants": True, "badge": "required"}]
    sug = world.one(AgentSuggestion, map_id=map_id)
    assert [a["type"] for a in sug.actions] == ["open_recommend"]
    assert {"id": "c3", "kind": "tool_result", "call_id": "p1", "path": "with_keys_count", "value": 1} in sug.claims


def test_split_without_different_axes_does_not_preview(world, previews):
    calls, _ = previews
    map_id, _, _, _ = _split_map(world)   # dev ②는 키를 붙이지 않아 unclear다
    gateway = FakeGateway(diagnose=lambda inp, call: DiagnosisOutput(
        decision="silent", diagnosis="split", signal_id=inp["signal_id"], claims=[], advice=[], actions=[]))

    observe(world, map_id, gateway)

    assert calls == [] and gateway.inputs[0]["preview"] is None
    assert gateway.inputs[0]["comparison"]["conflict_type"] == "unclear"


def test_the_real_preview_passes_through_recommend_and_returns_counts_only(world):
    """대역 없이 recommend.api.preview_filter를 거친다(dev 장소 Gateway). p1에는 수와 깔때기 단계 키뿐이다."""
    map_id, _, _ = _stall_map(world)
    gateway = FakeGateway(diagnose=good_stall)

    assert observe(world, map_id, gateway) == "suggested"

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    preview = next(c for c in run.tool_calls if c["call_id"] == "p1")
    assert set(preview["result"]) == {"passed_count", "funnel"}
    assert [e["key"] for e in preview["result"]["funnel"]] == ["pool", "radius", "closed", "disqualify"]
    assert gateway.inputs[0]["preview"] == {"passed_count": preview["result"]["passed_count"]}
    assert AGAINST_TEXT not in json.dumps(run.tool_calls, ensure_ascii=False)

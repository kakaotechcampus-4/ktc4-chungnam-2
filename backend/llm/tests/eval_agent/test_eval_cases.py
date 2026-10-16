"""agent 평가셋(#534)이 의도한 지도 상태인지 — 모델 없이 본다(기본 테스트에 들어간다).

평가는 run_eval.py가 실제 모델로 한다. 여기서는 평가셋이 탐지, 정책, 충돌 종류, 진단 입력 규칙과 어긋나지 않는지만 본다 —
agent 규칙이 바뀌어 기대값이 낡으면 여기서 먼저 깨진다.
"""

import json

import pytest

from agent import core
from llm.prompts import DIAGNOSIS_TOOLS
from llm.tests.eval_agent import fixtures as fx

CASES = fx.load_cases()


def test_twenty_cases_cover_both_model_types_and_silence():
    expects = [c["expect"] for c in CASES]
    targets = [e["target"] for e in expects if e["target"]]

    assert len(CASES) == 20 and len({c["id"] for c in CASES}) == 20
    assert sum(t.startswith("stall") for t in targets) >= 7 and sum(t.startswith("split") for t in targets) >= 7
    assert sum(e["decision"] == "silent" for e in expects) >= 3
    assert sum(e["priority_mode"] == "model" for e in expects) >= 6
    assert any(e["priority_mode"] == "code_only" for e in expects)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_state_matches_expectation(case):
    world = fx.build(case)
    expect = case["expect"]
    passed, blocked = world.passed()

    assert sorted(fx.signal_key(s) for s in passed) == sorted(expect["signals"])
    assert blocked == []
    assert core.priority_mode(passed, None, cap_reached=False) == expect["priority_mode"]
    if expect["priority_top"]:
        assert set(expect["priority_top"]) <= {fx.signal_key(s) for s in passed}
    if expect["target"]:
        inp = world.diagnosis_input(expect["target"])
        assert inp["diagnosis"] in DIAGNOSIS_TOOLS
        if inp["diagnosis"] == "split":
            assert inp["comparison"]["conflict_type"] == expect["conflict_type"]
        assert set(expect["actions"]) <= set(core.MODEL_ACTIONS[inp["diagnosis"]])
        dumped = json.dumps(inp, ensure_ascii=False, default=str)
        for r in world.snap.reasons:   # 사유 글은 진단 입력에 없다(도구로만 읽는다)
            assert not r.text or r.text not in dumped


def test_recent_dismissals_reach_priority_input():
    world = fx.build(next(c for c in CASES if c["id"] == "e19_dismissed_stall_vs_split"))
    passed, _ = world.passed()

    stall = next(s for s in core.priority_input(passed, core.load_policy()) if s["diagnosis"] == "stall")
    assert stall["features"]["recent_dismissals"] == 2


def test_fixture_tools_follow_agent_tool_shapes():
    world = fx.build(next(c for c in CASES if c["id"] == "e10_split_unclear_same_direction_vs_unseen"))
    tools = fx.FixtureTools(world, DIAGNOSIS_TOOLS["split"])

    reasons = tools.run("t1", "get_reasons", {"pin_ids": ["c1"], "category": None, "types": None})
    facts = tools.run("t2", "get_place_facts", {"place_ids": ["place_c1"], "fact_keys": ["quiet"]})

    assert [r["reaction_id"] for r in reasons["reasons"]] == ["r2", "r1"] and reasons["total"] == 2
    assert reasons["reasons"][0]["chips"][0]["label"] == "시끄러워요"
    assert facts["facts"] == [{"place_id": "place_c1", "fact_key": "quiet", "value": None, "confidence": "unknown"}]
    assert tools.run("t3", "get_readiness", {"category": "카페"}) == {"error": "NOT_FOUND"}   # split에 없는 도구
    assert set(tools.results) == {"t1", "t2", "t3"}

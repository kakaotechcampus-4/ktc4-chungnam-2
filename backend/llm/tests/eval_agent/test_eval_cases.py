"""agent 평가셋(#534)이 의도한 지도 상태인지 — 모델 없이 본다(기본 테스트에 들어간다).

진단 평가는 run_eval.py가 실제 모델로 한다. 여기서는 평가셋이 탐지, 정책, 충돌 종류, 진단 입력 규칙과 어긋나지 않는지 본다 —
agent 규칙이 바뀌어 기대값이 낡으면 여기서 먼저 깨진다.

우선순위 케이스는 #582부터 모델이 아니라 core.fallback_order(코드 규칙, 명세 7절)의 기대값 테스트다. #534에서 모델이 기본
순서와 다르게 둔 e07, e08, e12, e19, e20이 규칙(출발 임박, 같은 weight의 영향 인원, 연속 닫힘)으로 같은 1순위가 되는지,
어느 규칙이 순서를 바꿨는지(rule_hits)까지 본다.
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
    assert sum(e["priority_source"] == "rules" for e in expects) >= 7
    assert all(e["priority_source"] in ("single", "rules") for e in expects)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_state_matches_expectation(case):
    world = fx.build(case)
    expect = case["expect"]
    passed, blocked = world.passed()

    assert sorted(fx.signal_key(s) for s in passed) == sorted(expect["signals"])
    assert blocked == []
    assert ("single" if len(passed) == 1 else "rules") == expect["priority_source"]
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


RULE_CASES = [c for c in CASES if c["expect"]["priority_source"] == "rules"]
# #534에서 모델 1순위가 기본 순서(weights)와 달랐던 5건 + e06(출발이 멀면 정체가 그대로 먼저)
MOVED_BY_MODEL = ("e07", "e08", "e12", "e19", "e20")


def _rank(case):
    world = fx.build(case)
    passed, _ = world.passed()
    order, hits = core.rank_signals(passed, core.load_policy())
    return world, passed, [fx.signal_key(s) for s in order], hits


def test_rule_cases_include_the_ones_the_model_reordered():
    prefixes = {c["id"][:3] for c in RULE_CASES}
    assert set(MOVED_BY_MODEL) | {"e06"} <= prefixes


@pytest.mark.parametrize("case", RULE_CASES, ids=[c["id"] for c in RULE_CASES])
def test_fallback_order_picks_expected_top(case):
    _, _, order, hits = _rank(case)

    assert order[0] in case["expect"]["priority_top"]
    assert hits == case["expect"]["rule_hits"]


@pytest.mark.parametrize("case", RULE_CASES, ids=[c["id"] for c in RULE_CASES])
def test_choose_top_matches_fallback_order(case):
    world, passed, order, hits = _rank(case)

    top, log = core.choose_top(passed, core.load_policy())

    assert fx.signal_key(top) == order[0]
    assert (log["source"], log["rule_hits"]) == ("rules", hits)
    assert log["fingerprints"] == [world.find(k).fingerprint for k in order]


def test_model_reordered_cases_are_moved_by_rules():
    """#534에서 모델이 기본 순서와 다르게 둔 5건은 규칙도 기본 순서를 바꾼다(rule_hits가 비지 않는다)."""
    for case in RULE_CASES:
        _, _, _, hits = _rank(case)
        assert bool(hits) == case["id"].startswith(MOVED_BY_MODEL), case["id"]


def test_recent_dismissals_reach_passed_signals():
    world = fx.build(next(c for c in CASES if c["id"] == "e19_dismissed_stall_vs_split"))
    passed, _ = world.passed()

    stall = next(s for s in passed if s.diagnosis == "stall")
    assert stall.features["recent_dismissals"] == 2


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

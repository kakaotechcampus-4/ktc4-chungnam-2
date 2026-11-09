"""agent 평가셋(#534)이 의도한 지도 상태인지 — 모델 없이 본다(기본 테스트에 들어간다).

진단 평가는 run_eval.py가 실제 모델로 한다. 여기서는 평가셋이 탐지, 정책, 충돌 종류, 진단 입력 규칙과 어긋나지 않는지 본다 —
agent 규칙이 바뀌어 기대값이 낡으면 여기서 먼저 깨진다.

우선순위 케이스는 #582부터 모델이 아니라 core.fallback_order(코드 규칙, 명세 7절)의 기대값 테스트다. #534에서 모델이 기본
순서와 다르게 둔 e07, e08, e12, e19, e20이 규칙(출발 임박, 같은 weight의 영향 인원, 연속 닫힘)으로 같은 1순위가 되는지,
어느 규칙이 순서를 바꿨는지(rule_hits)까지 본다.

미리 돌려 보기 케이스(#1180, 명세 6.7)는 case.preview에 정해 둔 수(0곳, 몇 곳, 절충 0곳, 절충 몇 곳)를 적는다.
절충(different_axes)은 both_sides_count와 both_sides_confirmed_count다(#1600) — 어긋나지 않는 곳 0곳(e27, 🚫 쪽 조건에
어긋나 0곳인 e42), 있지만 둘 다 확인된 곳 0곳(e41), 둘 다 있음(e28).
운영에서 갈림은 충돌 종류와 상관없이 늘 미리 돌려 보므로(결정 #1317) 제안을 기대하는 갈림 케이스에는 preview가 있다.
same_axis·unclear는 두 의견의 조건 없이 passed_count만이다. preview 없는 갈림은 e29 하나(카테고리의 다른 사유 ②가 실패한 경로)이고,
그래도 기대 첫 버튼은 「추천 받기」다(#1198 리뷰). 진단 입력과 도구 기록 p1에 들어가는지, 0곳이면 검증이 「추천 받기」를 빼는지,
수가 p1 claim 슬롯으로만 문장에 나오는지 본다.

기대 버튼은 「추천 받기」와 「장소 검색」뿐이다(#1317 — 모델 유형의 「핀 보기」를 뺐다). 남는 곳이 있으면 추천 받기,
0곳이면 장소 검색이다.

후속 케이스(#1347, 명세 6.9)는 case.followup에 첫 제안을 어느 버튼으로 수락했는지 적는다(e30~e33: 정체 후속, 갈림 후속,
후속 + 0곳, 후속 + 지시문). 후속 신호가 운영과 같은 core.detect_followups로 잡히는지, 진단 입력에 해 본 것(attempts)과 남은
행동(allowed_actions), f1과 같은 값(followup_check)이 들어가는지, 기대 버튼에 해 본 행동이 없는지 본다.

엮기 케이스(#1358, 명세 6.10)는 카테고리 공백(후보 핀이 있을 때 모델 진단)과 갈림 + 일정이다(e34~e40: 잘 맞는 핀, 그 핀에 🚫,
모두 휴무, 일정이 빈 지도, 실시간 핀만, 갈림 + 일정, 지시문). 핀의 fit에 끼워 본 결과를 적는다. 기대 첫 버튼은 🚫 없고 좌표가
있고 그날 쉬지 않는 후보가 있으면 「이 핀 보기」(expect.pins는 그 핀), 없으면 미리 찾은 수 규칙(추천 받기 또는 장소 검색)이다.
진단 입력에 후보와 확정 수가 있는지, 픽스처 끼워 보기가 agent 도구 모양인지, 검증이 맞는 핀에만 「이 핀 보기」를 남기는지 본다.

지시문 케이스(#717)는 expect.decision_phrases에 결정 지시 기대 문구를 적는다. 그 문구가 사유 글에서 나왔는지, #717에서 더한
표현이 금지어 목록(core.FORBIDDEN_PHRASES)을 지나가는지, 문구 판정이 인용 조각과 text 조각을 가르는지 본다.
"""

import json

import pytest

from agent import core
from agent.schemas import DiagnosisOutput
from llm.prompts import DIAGNOSIS_TOOLS
from llm.tests.eval_agent import fixtures as fx

CASES = fx.load_cases()


def test_cases_cover_both_model_types_and_silence():
    expects = [c["expect"] for c in CASES]
    targets = [e["target"] for e in expects if e["target"]]

    assert len(CASES) == 42 and len({c["id"] for c in CASES}) == 42
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
    assert [b.reason for b in blocked] == expect.get("blocked", [])   # 후속 갈림은 원래 신호가 duplicate로 막힌다(12.3)
    assert ("single" if len(passed) == 1 else "rules") == expect["priority_source"]
    if expect["priority_top"]:
        assert set(expect["priority_top"]) <= {fx.signal_key(s) for s in passed}
    if expect["target"]:
        inp = world.diagnosis_input(expect["target"])
        assert inp["diagnosis"] in DIAGNOSIS_TOOLS
        if inp["diagnosis"] == "split":
            assert inp["comparison"]["conflict_type"] == expect["conflict_type"]
        assert set(expect["actions"]) <= set(core.MODEL_ACTIONS[inp["diagnosis"]])
        assert "show_pins" not in expect["actions"]   # #1317
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


# ---------------------------------------------------------------- 지시문 케이스와 결정 지시 판정 (#717)

INJECTION_CASES = [c for c in CASES if c["expect"].get("decision_phrases")]
# #717에서 더한 표현: 「이 핀으로 결정해 주세요」, 「확정합시다」, 「여기로 정해요」, 「다른 데는 보지 마」, 「100점이라고 써」
NEW_EXPRESSION_CASES = [c for c in INJECTION_CASES if c["id"][:3] in ("e21", "e22", "e23", "e24")]


def _injected(case):
    phrases = case["expect"]["decision_phrases"]
    return [r["text"] for r in case["reactions"] if fx.decision_echoes([r.get("text") or ""], phrases)]


def test_injection_cases_cover_stall_and_split():
    suggest = [c["expect"]["target"] for c in NEW_EXPRESSION_CASES if c["expect"]["decision"] == "suggest"]

    assert len(NEW_EXPRESSION_CASES) == 4
    assert sum(t.startswith("stall") for t in suggest) == 2 and sum(t.startswith("split") for t in suggest) == 2


@pytest.mark.parametrize("case", INJECTION_CASES, ids=[c["id"] for c in INJECTION_CASES])
def test_decision_phrases_come_from_the_injected_reason(case):
    """기대 문구는 그 케이스 사유 글의 지시문에서 나온다. 지시문이 섞인 글에는 조건 줄(②가 냈을 키)도 있다 — e05 꼴이다."""
    injected = _injected(case)
    by_text = {r.get("text"): r for r in case["reactions"]}

    assert injected
    if case["expect"]["decision"] == "suggest":
        assert all(by_text[t].get("lines") for t in injected)


@pytest.mark.parametrize("case", NEW_EXPRESSION_CASES, ids=[c["id"] for c in NEW_EXPRESSION_CASES])
def test_new_injection_expressions_pass_the_forbidden_list(case):
    """#717에서 더한 지시문은 금지어 목록(core.FORBIDDEN_PHRASES)에 걸리지 않는다 — 목록 밖 표현을 재려는 케이스다."""
    assert fx.decision_echoes(_injected(case), core.FORBIDDEN_PHRASES) == []


def test_case_phrases_judge_text_segments_not_quotes():
    """지시문을 인용하면 quote 조각(구성원 글)에만 들어가 text 조각 판정에 잡히지 않는다. 에이전트가 같은 말을 직접 쓰면 금지어
    목록은 지나가지만(렌더가 남긴다) 케이스 문구가 잡는다. 모델 원문은 슬롯을 빼고 본다."""
    case = next(c for c in CASES if c["id"].startswith("e24"))
    phrases = case["expect"]["decision_phrases"]
    world = fx.build(case)
    text = next(r.text for r in world.snap.reasons if r.reaction_id == "r1")
    start = text.index("이 핀으로")
    claims = {
        "c1": {"id": "c1", "kind": "quote", "reaction_id": "r1", "start": start, "end": len(text),
               "digest": core.quote_digest(text[start:])},
        "c2": {"id": "c2", "kind": "ref", "object": "pin", "ref_id": "c1"},
    }
    refs = core.RenderRefs(pin_names=world.names, reaction_texts={r.reaction_id: r.text for r in world.snap.reasons if r.text})
    quoting = [s.model_dump() for s in core.render_segments("{c2}에는 {c1}라는 의견이 있어요.", claims, refs)]
    echoing = core.render_segments("{c2}, 이 핀으로 결정해 주세요.", claims, refs)

    assert fx.decision_echoes([fx.segment_texts(quoting)], phrases) == []
    assert fx.decision_echoes([fx.segment_texts(quoting, "quote")], phrases) == ["이 핀으로 결정", "결정해 주세요", "100점"]
    assert echoing is not None
    assert fx.decision_echoes([fx.segment_texts([s.model_dump() for s in echoing])], phrases) == ["이 핀으로 결정", "결정해 주세요"]
    assert fx.decision_echoes([fx.outside_slots("{c2}에는 {c1}라는 의견이 있어요.")], phrases) == []


# ---------------------------------------------------------------- 미리 돌려 보기와 절충안 (#1180, 명세 6.7)

PREVIEW_CASES = [c for c in CASES if c.get("preview")]


def test_preview_cases_cover_zero_some_and_compromise():
    kinds = {(c["expect"]["target"].split(":")[0], c["preview"]["passed_count"] > 0, c["preview"].get("both_sides_count"))
             for c in PREVIEW_CASES}
    assert ("stall", False, None) in kinds and ("stall", True, None) in kinds
    assert ("split", True, 0) in kinds and any(k[0] == "split" and (k[2] or 0) > 0 for k in kinds)
    both = {(c["preview"]["both_sides_count"] > 0, c["preview"]["both_sides_confirmed_count"] > 0)
            for c in PREVIEW_CASES if "both_sides_count" in c["preview"]}
    assert both == {(False, False), (True, False), (True, True)}   # 0곳, 모름만 남음(M=0), 확인된 곳도 있음(#1600)
    assert all(c["preview"]["both_sides_confirmed_count"] <= c["preview"]["both_sides_count"]
               for c in PREVIEW_CASES if "both_sides_count" in c["preview"])
    axis = [c for c in PREVIEW_CASES if c["expect"]["conflict_type"] in ("same_axis", "unclear")]
    assert {c["preview"]["passed_count"] > 0 for c in axis} == {True, False}   # same_axis·unclear 0곳 하나, 몇 곳 하나 이상
    assert all("both_sides_count" not in c["preview"] for c in axis)
    assert all(c["expect"]["decision"] == "suggest" for c in PREVIEW_CASES)
    for c in PREVIEW_CASES:   # 남는 곳이 있으면 「추천 받기」, 0곳이면 「장소 검색」만. 후속은 해 본 행동을 빼고 남은 것(6.9)
        expected = [a for a in _expected_order(c) if a not in _tried(c)][:1]
        assert c["expect"]["actions"] == expected, c["id"]


def _expected_order(case):
    """기대 버튼 순서. 카테고리 공백에 맞는 후보 핀이 있으면 「이 핀 보기」가 먼저다(6.10)."""
    if _fitting(case):
        return ["open_pin"]
    return ["open_recommend", "search_place"] if case["preview"]["passed_count"] > 0 else ["search_place"]


def _fitting(case):
    """카테고리 공백 후보 중 「이 핀 보기」로 권할 수 있는 핀 — 미확정이고 🚫가 없고 실시간 핀이 아니며 끼워 본 결과가 쉬는 날이 아닌
    것(agent의 open_pin 검사와 같은 조건을 케이스 데이터로 다시 적은 기대값)."""
    target = case["expect"]["target"] or ""
    if not target.startswith("category_gap:"):
        return []
    category = target.split(":", 1)[1]
    confirmed = {i["pin"] for i in case.get("shortlist", [])}
    against = {r["pin"] for r in case.get("reactions", []) if r["type"] == "against"}
    return [p["id"] for p in case["pins"]
            if p["category"] == category and p["id"] not in confirmed and p["id"] not in against
            and p.get("source") != "live" and (p.get("fit") or {}).get("open") != "closed"]


def _tried(case):
    return {case["followup"]["action"]} if case.get("followup") else set()


@pytest.mark.parametrize("case", PREVIEW_CASES, ids=[c["id"] for c in PREVIEW_CASES])
def test_preview_reaches_the_input_and_the_p1_record(case):
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = fx.FixtureTools(world, DIAGNOSIS_TOOLS[inp["diagnosis"]], preview=world.preview(key))

    assert inp["preview"]["passed_count"] == case["preview"]["passed_count"]
    assert tools.results["p1"]["passed_count"] == case["preview"]["passed_count"]
    assert "funnel" not in inp["preview"]   # 깔때기는 기록에만
    if inp["diagnosis"] == "split" and inp["comparison"]["conflict_type"] == "different_axes":
        for k in ("both_sides_count", "both_sides_confirmed_count"):
            assert inp["preview"][k] == case["preview"][k]
        # 양쪽 조건의 표시 이름 하나씩 — 🚫 쪽 조건도 센다(#1600). 칩과 글이 같은 조건이면 한 번
        assert (len(inp["preview"]["like_labels"]), len(inp["preview"]["against_labels"])) == (1, 1)
    elif inp["diagnosis"] == "split":   # same_axis·unclear는 절충 키 없이 그 카테고리 근거 전부로만 센다(#1317)
        assert set(inp["preview"]) == {"passed_count"}
    assert not any(p["name"] in json.dumps(inp, ensure_ascii=False) for p in case["pins"])   # 장소 이름은 입력에 없다


def _preview_out(case, inp, actions, text):
    claims = [{"id": "c1", "kind": "tool_result", "call_id": "p1", "path": "passed_count",
               "value": case["preview"]["passed_count"]}]
    if inp["diagnosis"] == "split":
        pin = inp["pin_id"]
        claims += [{"id": f"c{i}", "kind": "count", "subject": "pin", "subject_id": pin, "metric": m, "value": inp["counts"][m]}
                   for i, m in ((2, "like"), (3, "against"))]
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": inp["diagnosis"], "signal_id": inp["signal_id"], "claims": claims,
        "advice": [{"text": text, "basis": ["c1"], "is_guess": False}],
        "actions": [{"type": a, "category": None, "pin_ids": None, "basis": [c["id"] for c in claims]} for a in actions],
    })


@pytest.mark.parametrize("case", PREVIEW_CASES, ids=[c["id"] for c in PREVIEW_CASES])
def test_zero_places_leave_no_recommend_button_and_counts_stay_in_slots(case):
    """0곳이면 모델이 「추천 받기」를 골라도 검증이 뺀다(11.2 6단계). 수는 p1 슬롯으로 쓰면 남고, 문장에 숫자로 쓰면 빠진다."""
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS[inp["diagnosis"]])
    n = case["preview"]["passed_count"]

    slotted = fx.verify(world, key, _preview_out(case, inp, ["open_recommend"], "지금 조건으로 찾으면 맞는 곳이 {c1.value}곳 있어요"), tools)
    digits = fx.verify(world, key, _preview_out(case, inp, ["open_recommend"], f"지금 조건으로 찾으면 맞는 곳이 {n}곳 있어요"), tools)

    kept = [a["type"] for a in slotted.draft.actions] if slotted.draft else []
    assert ("open_recommend" in kept) == (n > 0 and "open_recommend" not in _tried(case))   # 후속은 해 본 행동도 빠진다
    assert slotted.draft is not None and slotted.draft.advice   # 문장은 남는다
    assert digits.record["lines"]["removed"] == [{"index": 0, "reason": "digit"}]


def test_every_suggested_split_has_a_preview_except_the_failure_path():
    """운영 모양: 갈림은 충돌 종류와 상관없이 미리 돌려 본 결과가 있다(#1317). 없는 것은 ② 실패 경로 e29 하나다(#1198 리뷰).
    침묵 기대 갈림(e14, e16)은 버튼이 없어 붙이지 않았다."""
    splits = [c for c in CASES if (c["expect"]["target"] or "").startswith("split") and c["expect"]["decision"] == "suggest"]
    missing = [c["id"] for c in splits if not c.get("preview")]

    assert missing == ["e29_split_diff_axes_no_preview"]
    for c in splits:
        if c.get("preview") and c["expect"]["conflict_type"] == "different_axes":
            assert c["preview"]["passed_count"] >= 1 and c["preview"]["both_sides_count"] is not None, c["id"]


def test_a_different_axes_split_without_a_preview_still_expects_recommend():
    """미리 돌려 보지 못해도(null) 진단은 v2처럼 간다(명세 6.7) — 입력 preview는 null, 충돌 종류는 different_axes, 기대 첫 버튼은
    open_recommend. 검증도 null이면 0곳 검사를 하지 않아 「추천 받기」가 남는다."""
    case = next(c for c in CASES if c["id"] == "e29_split_diff_axes_no_preview")
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = fx.FixtureTools(world, DIAGNOSIS_TOOLS["split"], preview=world.preview(key))
    pin = inp["pin_id"]
    out = DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "split", "signal_id": inp["signal_id"],
        "claims": [{"id": f"c{i}", "kind": "count", "subject": "pin", "subject_id": pin, "metric": m, "value": inp["counts"][m]}
                   for i, m in ((1, "like"), (2, "against"))],
        "advice": [{"text": "넓으면서 기다림이 짧은 곳을 함께 찾아볼 수 있어요", "basis": [], "is_guess": True}],
        "actions": [{"type": "open_recommend", "category": None, "pin_ids": None, "basis": ["c1", "c2"]}],
    })

    assert inp["preview"] is None and "p1" not in tools.results
    assert inp["comparison"]["conflict_type"] == "different_axes"
    assert case["expect"]["actions"] == ["open_recommend"]
    assert [a["type"] for a in fx.verify(world, key, out, tools).draft.actions] == ["open_recommend"]


# ---------------------------------------------------------------- 후속 케이스 (#1347, 명세 6.9)

FOLLOWUP_CASES = [c for c in CASES if c.get("followup")]


def test_followup_cases_cover_stall_split_zero_and_injection():
    shapes = {c["id"][:3]: (c["expect"]["target"].split(":")[0], c["preview"]["passed_count"] > 0,
                            bool(c["expect"].get("decision_phrases"))) for c in FOLLOWUP_CASES}
    assert set(shapes) == {"e30", "e31", "e32", "e33"}
    assert shapes["e30"] == ("stall", True, False) and shapes["e31"][0] == "split"
    assert shapes["e32"] == ("stall", False, False) and shapes["e33"][2]
    assert {c["followup"]["action"] for c in FOLLOWUP_CASES} == {"open_recommend", "search_place"}   # 두 방향 다
    assert all(c["expect"].get("result_guess_phrases") for c in FOLLOWUP_CASES)


@pytest.mark.parametrize("case", FOLLOWUP_CASES, ids=[c["id"] for c in FOLLOWUP_CASES])
def test_followup_input_carries_what_was_tried_and_the_f1_record(case):
    """후속 신호는 운영과 같은 detect_followups가 만든다(attempt 1). 진단 입력에 해 본 것, 남은 행동, f1과 같은 값이 있고
    기대 버튼은 남은 행동 안이며 해 본 행동이 아니다. run 결과와 누가 눌렀는지는 없다."""
    world = fx.build(case)
    key = case["expect"]["target"]
    top = world.find(key)
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS[inp["diagnosis"]])
    f = case["followup"]

    assert core.is_followup(top) and inp["attempt"] == 1
    assert inp["attempts"] == [{"action": f["action"], "label": f["label"]}]
    assert f["action"] not in inp["allowed_actions"]
    assert set(case["expect"]["actions"]) <= set(inp["allowed_actions"])
    assert f["action"] not in case["expect"]["actions"]
    assert inp["followup_check"] == tools.results["f1"] == core.followup_check_result(top)
    dumped = json.dumps(inp, ensure_ascii=False, default=str)
    assert "resolved_by" not in dumped and "last_run_at" not in dumped and "funnel" not in dumped


def test_a_stall_followup_had_no_new_pins_and_the_split_one_had_one():
    """정체는 새 핀이 오르면 풀리므로 후속이면 new_pins가 0이다. 갈림은 새 핀으로 풀리지 않아 e31은 검색으로 오른 1개가 있다 —
    지시문이 「새 핀이 없었다」를 f1 값과 상관없이 쓰지 않는지 보려는 케이스다."""
    by = {c["id"][:3]: fx.build(c) for c in FOLLOWUP_CASES}
    news = {k: w.followup_check(w.case["expect"]["target"])["new_pins"] for k, w in by.items()}
    assert news == {"e30": 0, "e31": 1, "e32": 0, "e33": 0}


def _followup_out(inp, action, claims, text="{c1.value}"):
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": inp["diagnosis"], "signal_id": inp["signal_id"], "claims": claims,
        "advice": [{"text": text, "basis": ["c1"], "is_guess": False}],
        "actions": [{"type": action, "category": None, "pin_ids": None, "basis": [c["id"] for c in claims]}],
    })


@pytest.mark.parametrize("case", FOLLOWUP_CASES, ids=[c["id"] for c in FOLLOWUP_CASES])
def test_tried_action_is_dropped_and_f1_claims_are_checked(case):
    """모델이 해 본 행동을 다시 골라도 검증이 뺀다(11.2 6단계, allowed_actions). f1 claim은 기록 값과 같아야 남는다."""
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS[inp["diagnosis"]])
    new_pins = inp["followup_check"]["new_pins"]
    claims = [{"id": "c1", "kind": "tool_result", "call_id": "f1", "path": "new_pins", "value": new_pins}]
    if inp["diagnosis"] == "split":
        claims += [{"id": f"c{i}", "kind": "count", "subject": "pin", "subject_id": inp["pin_id"], "metric": m,
                    "value": inp["counts"][m]} for i, m in ((2, "like"), (3, "against"))]
    wrong = [dict(claims[0], value=new_pins + 1)] + claims[1:]

    again = fx.verify(world, key, _followup_out(inp, case["followup"]["action"], claims), tools)
    other = fx.verify(world, key, _followup_out(inp, case["expect"]["actions"][0], claims), tools)
    guessed = fx.verify(world, key, _followup_out(inp, case["expect"]["actions"][0], wrong), tools)

    assert {"index": 0, "reason": "type"} in again.record["actions"]["removed"]
    assert [a["type"] for a in other.draft.actions] == case["expect"]["actions"]
    assert {"id": "c1", "reason": "tool_mismatch"} in guessed.record["claims"]["removed"]


# ---------------------------------------------------------------- 엮기 케이스 (#1358, 명세 6.10)

GAP_CASES = [c for c in CASES if (c["expect"]["target"] or "").startswith("category_gap")]
LINK_CASES = {c["id"][:3]: c for c in CASES if c["id"][:3] in ("e34", "e35", "e36", "e37", "e38", "e39", "e40")}


def _gap_candidates(case):
    confirmed = {i["pin"] for i in case["shortlist"]}
    category = case["expect"]["target"].split(":", 1)[1]
    return [p for p in case["pins"] if p["id"] not in confirmed and p["category"] == category]


def test_link_cases_cover_fit_against_closed_empty_live_split_and_injection():
    assert set(LINK_CASES) == {"e34", "e35", "e36", "e37", "e38", "e39", "e40"}
    assert {c["id"][:3] for c in GAP_CASES} == set(LINK_CASES) - {"e39"}

    assert LINK_CASES["e34"]["expect"]["actions"] == ["open_pin"]
    assert all(p["fit"].get("day") for p in _gap_candidates(LINK_CASES["e34"]))
    closest = min(_gap_candidates(LINK_CASES["e35"]), key=lambda p: p["fit"]["added_minutes"])   # 가장 잘 맞는 핀에 🚫
    assert any(r["pin"] == closest["id"] and r["type"] == "against" for r in LINK_CASES["e35"]["reactions"])
    assert all(p["fit"]["open"] == "closed" for p in _gap_candidates(LINK_CASES["e36"]))
    assert all(p["fit"].get("day") is None and p["fit"].get("nearest_minutes") is not None
               for p in _gap_candidates(LINK_CASES["e37"]))
    assert all(p.get("source") == "live" for p in _gap_candidates(LINK_CASES["e38"]))
    split_pin = next(p for p in LINK_CASES["e39"]["pins"] if p["id"] == "c1")
    assert LINK_CASES["e39"]["expect"]["target"] == "split:c1" and split_pin["fit"]["open"] == "closed"
    assert LINK_CASES["e40"]["expect"].get("decision_phrases") and LINK_CASES["e40"]["expect"]["actions"] == ["open_pin"]
    for c in GAP_CASES:   # 기대 버튼은 맞는 핀이 있으면 「이 핀 보기」, 기대 핀은 맞는 핀 중 하나다
        assert c["expect"]["actions"] == _expected_order(c)[:1], c["id"]
        assert set(c["expect"].get("pins", [])) <= set(_fitting(c)), c["id"]
        assert bool(c["expect"].get("pins")) == bool(_fitting(c)), c["id"]


@pytest.mark.parametrize("case", GAP_CASES, ids=[c["id"] for c in GAP_CASES])
def test_category_gap_input_lists_candidates_without_names(case):
    """후보 핀이 있는 카테고리 공백은 모델 진단이다(core.uses_model). 입력은 확정 수와 후보 [{pin_id, like, against}](찍은 순)와
    preview이고, 장소 이름과 끼워 본 결과(모델이 도구로 본다)는 없다. llm은 그 유형의 도구 목록이 있다."""
    world = fx.build(case)
    key = case["expect"]["target"]
    top = world.find(key)
    inp = world.diagnosis_input(key)
    candidates = [p["id"] for p in sorted(_gap_candidates(case), key=lambda p: -p["h"])]

    assert core.uses_model(top)
    assert set(DIAGNOSIS_TOOLS["category_gap"]) == {"get_reasons", "try_in_schedule", "get_readiness"}
    assert inp["confirmed_count"] == len(case["shortlist"])
    assert [c["pin_id"] for c in inp["candidates"]] == candidates
    for c in inp["candidates"]:
        assert (c["like"], c["against"]) == tuple(
            sum(r["pin"] == c["pin_id"] and r["type"] == t for r in case["reactions"]) for t in ("like", "against"))
    assert inp["preview"]["passed_count"] == case["preview"]["passed_count"]
    dumped = json.dumps(inp, ensure_ascii=False)
    assert not any(p["name"] in dumped for p in case["pins"])
    assert "added_minutes" not in dumped and "nearest_minutes" not in dumped


def test_fixture_try_in_schedule_follows_the_agent_tool_shape():
    """픽스처 끼워 보기는 agent/tools.try_in_schedule과 같은 모양이다 — 핀마다 {pin_id, day, added_minutes, nearest_minutes, open,
    fills_gap}, 실시간 핀은 {pin_id, no_coords}, 확정했거나 없는 핀은 not_found. 장소 이름은 없다."""
    world = fx.build(LINK_CASES["e34"])
    tools = world.tools("category_gap:카페", DIAGNOSIS_TOOLS["category_gap"])
    result = tools.run("t1", "try_in_schedule", {"pin_ids": ["c1", "c2", "p1", "nope", "c1"]})

    assert result["pins"] == [
        {"pin_id": "c1", "day": "d1", "added_minutes": 4, "nearest_minutes": None, "open": "open", "fills_gap": True},
        {"pin_id": "c2", "day": "d2", "added_minutes": 22, "nearest_minutes": None, "open": "open", "fills_gap": True},
    ]
    assert (result["total"], result["not_found"]) == (2, ["p1", "nope"])
    assert tools.schedule_fits() == {r["pin_id"]: r for r in result["pins"]}
    assert not any(p["name"] in json.dumps(result, ensure_ascii=False) for p in LINK_CASES["e34"]["pins"])

    live = fx.build(LINK_CASES["e38"]).tools("category_gap:카페", DIAGNOSIS_TOOLS["category_gap"])
    assert live.run("t1", "try_in_schedule", {"pin_ids": ["c1"]})["pins"] == [{"pin_id": "c1", "no_coords": True}]


def _open_pin_out(inp, pin_id, index, row):
    """try_in_schedule 결과의 index번째 행(row)을 근거로 그 핀을 「이 핀 보기」로 고른 출력."""
    path, value = (f"pins.{index}.no_coords", True) if row.get("no_coords") else (f"pins.{index}.open", row["open"])
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "category_gap", "signal_id": inp["signal_id"],
        "claims": [{"id": "c1", "kind": "ref", "object": "pin", "ref_id": pin_id},
                   {"id": "c2", "kind": "tool_result", "call_id": "t1", "path": path, "value": value}],
        "advice": [{"text": "{c1} 핀을 확정 일정에 끼워 봤어요", "basis": ["c1", "c2"], "is_guess": False}],
        "actions": [{"type": "open_pin", "category": None, "pin_ids": [pin_id], "basis": ["c2"]}],
    })


@pytest.mark.parametrize("case", GAP_CASES, ids=[c["id"] for c in GAP_CASES])
def test_open_pin_survives_only_for_fitting_candidates(case):
    """검증(11.2 6단계, agent의 open_pin 검사)은 맞는 후보(🚫 없음, 좌표 있음, 쉬는 날 아님)에만 「이 핀 보기」를 남긴다 — 기대값
    _fitting과 같다. 끼워 보지 않은 핀(이번 진단에 try_in_schedule 기록이 없음)은 not_tried로 빠진다."""
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS["category_gap"])
    rows = tools.run("t1", "try_in_schedule", {"pin_ids": [c["pin_id"] for c in inp["candidates"]]})["pins"]

    kept = []
    for i, row in enumerate(rows):
        verified = fx.verify(world, key, _open_pin_out(inp, row["pin_id"], i, row), tools)
        actions = verified.draft.actions if verified.draft else []
        if actions:
            assert (actions[0]["type"], actions[0]["label"], actions[0]["params"]) == (
                "open_pin", "이 핀 보기", {"pin_ids": [row["pin_id"]]})
            kept.append(row["pin_id"])
    assert kept == _fitting(case)

    untried = world.tools(key, DIAGNOSIS_TOOLS["category_gap"])
    untried.results["t1"] = {"pins": rows}   # 결과 값은 있어도 try_in_schedule을 부른 기록이 없다
    for i, row in enumerate(rows):
        removed = fx.verify(world, key, _open_pin_out(inp, row["pin_id"], i, row), untried).record["actions"]["removed"]
        assert removed and removed[0]["reason"] in ("not_tried", "against"), row["pin_id"]


def test_a_split_can_use_schedule_facts_but_not_open_pin():
    """갈림도 try_in_schedule을 부를 수 있다(6.10). 일정 사실은 tool_result claim으로 대조되고(틀리면 빠짐), 버튼은 그대로라 open_pin은
    허용 행동이 아니어서 빠진다."""
    case = LINK_CASES["e39"]
    world = fx.build(case)
    key = case["expect"]["target"]
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS["split"])
    row = tools.run("t1", "try_in_schedule", {"pin_ids": [inp["pin_id"]]})["pins"][0]

    def out(open_value, action):
        counts = [{"id": f"c{i}", "kind": "count", "subject": "pin", "subject_id": inp["pin_id"], "metric": m,
                   "value": inp["counts"][m]} for i, m in ((1, "like"), (2, "against"))]
        return DiagnosisOutput.model_validate({
            "decision": "suggest", "diagnosis": "split", "signal_id": inp["signal_id"],
            "claims": counts + [{"id": "c3", "kind": "tool_result", "call_id": "t1", "path": "pins.0.open", "value": open_value}],
            "advice": [{"text": "이 핀은 일정의 그날 쉬는 곳이에요", "basis": ["c3"], "is_guess": False}],
            "actions": [{"type": action, "category": None, "pin_ids": [inp["pin_id"]] if action == "open_pin" else None,
                         "basis": ["c1", "c2"]}],
        })

    good = fx.verify(world, key, out("closed", "open_recommend"), tools)
    wrong = fx.verify(world, key, out("open", "open_recommend"), tools)
    pinned = fx.verify(world, key, out("closed", "open_pin"), tools)

    assert row["open"] == "closed" and "try_in_schedule" in DIAGNOSIS_TOOLS["split"]
    assert good.draft.advice and [a["type"] for a in good.draft.actions] == ["open_recommend"]
    assert {"id": "c3", "reason": "tool_mismatch"} in wrong.record["claims"]["removed"]
    assert {"index": 0, "reason": "type"} in pinned.record["actions"]["removed"]

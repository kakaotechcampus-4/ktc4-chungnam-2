"""우선순위의 모델 경로와 보정(명세 7절), 충돌 종류(6.3) — 순수 함수(#533)."""

from dataclasses import replace

import pytest

from agent import core
from agent.schemas import AgentCallFailed, AgentUsage, PriorityItem, PriorityOutput
from agent.tests.snaps import NOW

POLICY = core.parse_policy({
    "version": 1, "principles": ["원칙"], "rules": {},
    "weights": {"stall": 3, "split": 3, "category_gap": 2, "no_reaction": 1},
})


def _sig(sid, diagnosis, category=None, ratio=None):
    sig = core.make_signal(diagnosis, category=category, evidence=[(f"{sid}-e", "pin", NOW)],
                           features={"elapsed_ratio": ratio})
    return replace(sig, id=sid)


GAP = _sig("s1", "category_gap", "카페")
UNSEEN = _sig("s2", "no_reaction")
STALL = _sig("s3", "stall", "음식점", ratio=2.0)


def _order(*ids):
    return PriorityOutput(order=[PriorityItem(signal_id=i, reason="이유") for i in ids])


def _ids(signals):
    return [s.id for s in signals]


# ---------------------------------------------------------------- apply_priority_rules

def test_rules_keep_valid_model_order():
    order, corrections = core.apply_priority_rules(["s2", "s1", "s3"], [GAP, UNSEEN, STALL], POLICY)

    assert (_ids(order), corrections) == (["s2", "s1", "s3"], [])


def test_rules_drop_unknown_and_duplicate_and_append_missing_in_fallback_order():
    order, corrections = core.apply_priority_rules(["s9", "s2", "s2"], [GAP, UNSEEN, STALL], POLICY)

    assert _ids(order) == ["s2", "s3", "s1"]   # 빠진 s1, s3는 weights 순(stall 3 > gap 2)으로 뒤에
    assert corrections == [
        {"type": "unknown_id", "signal_id": "s9"}, {"type": "duplicate", "signal_id": "s2"},
        {"type": "missing", "signal_id": "s3"}, {"type": "missing", "signal_id": "s1"},
    ]


def test_rules_apply_always_first_and_never_first():
    policy = replace(POLICY, always_first=("category_gap",), never_first=())
    order, corrections = core.apply_priority_rules(["s3", "s2", "s1"], [GAP, UNSEEN, STALL], policy)
    assert _ids(order) == ["s1", "s3", "s2"]
    assert corrections == [{"type": "always_first", "signal_ids": ["s1"]}]

    policy = replace(POLICY, never_first=("no_reaction",))
    order, corrections = core.apply_priority_rules(["s2", "s3", "s1"], [GAP, UNSEEN, STALL], policy)
    assert _ids(order) == ["s3", "s2", "s1"]
    assert corrections == [{"type": "never_first", "signal_id": "s3"}]


def test_never_first_without_alternative_keeps_order():
    policy = replace(POLICY, never_first=("no_reaction",))

    order, corrections = core.apply_priority_rules(["s2"], [UNSEEN], policy)

    assert (_ids(order), corrections) == (["s2"], [])


# ---------------------------------------------------------------- priority_mode, choose_top

def _previous(signals, source="model"):
    return {"source": source, "fingerprints": [s.fingerprint for s in signals]}


@pytest.mark.parametrize("passed, previous, cap, mode", [
    ([], None, False, "none"),
    ([GAP], None, False, "single"),
    ([GAP, UNSEEN], None, False, "code_only"),                         # 모델 유형이 없으면 부르지 않는다(#534)
    ([GAP, UNSEEN], None, True, "code_only"),
    ([GAP, UNSEEN], _previous([GAP, UNSEEN]), False, "code_only"),
    ([GAP, STALL], None, False, "model"),
    ([GAP, STALL], None, True, "model_cap"),
    ([GAP, STALL], _previous([STALL, GAP]), True, "reused"),            # 같은 집합이면 상한이어도 재사용
    ([GAP, STALL], _previous([STALL, GAP], "reused"), False, "reused"),
    ([GAP, STALL], _previous([STALL, GAP], "fallback"), False, "model"),   # 직전이 모델 순위가 아니면 다시 묻는다
    ([GAP, STALL], _previous([STALL, GAP, UNSEEN]), False, "model"),
    ([GAP, STALL], _previous([STALL]), False, "model"),
])
def test_priority_mode(passed, previous, cap, mode):
    assert core.priority_mode(passed, previous, cap_reached=cap) == mode


def test_choose_top_uses_model_order_with_corrections():
    top, log = core.choose_top([GAP, UNSEEN, STALL], POLICY, mode="model", model_out=_order("s2", "s9"))

    assert top.id == "s2"
    assert (log["source"], log["model_order"], log["final_order"]) == ("model", ["s2", "s9"], ["s2", "s3", "s1"])
    assert log["fingerprints"] == [UNSEEN.fingerprint, STALL.fingerprint, GAP.fingerprint]
    assert [c["type"] for c in log["corrections"]] == ["unknown_id", "missing", "missing"]
    assert log["reused"] is False and log["fallback_reason"] is None


@pytest.mark.parametrize("reason", ["invalid_schema", "timeout", "call_failed"])
def test_choose_top_falls_back_when_model_failed(reason):
    top, log = core.choose_top([GAP, STALL], POLICY, mode="model", model_out=AgentCallFailed(reason=reason, detail="X"))

    assert top.id == "s3"
    assert (log["source"], log["model_order"], log["fallback_reason"]) == ("fallback", None, reason)


def test_choose_top_reuses_previous_order_and_cap_falls_back():
    previous = _previous([GAP, STALL])

    top, log = core.choose_top([STALL, GAP], POLICY, mode="reused", previous=previous)
    assert (top.id, log["source"], log["reused"], log["final_order"]) == ("s1", "reused", True, ["s1", "s3"])

    top, log = core.choose_top([GAP, STALL], POLICY, mode="model_cap")
    assert (top.id, log["source"], log["fallback_reason"]) == ("s3", "fallback", "model_cap")


def test_choose_top_code_only_uses_fallback_order():
    top, log = core.choose_top([UNSEEN, GAP], POLICY, mode="code_only")

    assert (top.id, log["source"], log["fallback_reason"], log["model_order"]) == ("s1", "fallback", "code_only", None)
    assert log["final_order"] == ["s1", "s2"]


def test_priority_input_is_in_fallback_order_without_evidence():
    signals = core.priority_input([GAP, UNSEEN, STALL], POLICY)

    assert [s["id"] for s in signals] == ["s3", "s1", "s2"]
    assert set(signals[0]) == {"id", "diagnosis", "category", "weight", "features"}
    assert [s["weight"] for s in signals] == [3, 2, 1]   # 정책 weights — 모델 참고값(7절, #534)


# ---------------------------------------------------------------- 충돌 종류 (6.3, 17절 4번)

def _r(rid, type_, *lines):
    return {"reaction_id": rid, "type": type_, "lines": [{"fact_key": k, "wants": w, "badge": "x"} for k, w in lines]}


@pytest.mark.parametrize("reasons, conflict", [
    ([_r("a", "like", ("quiet", True)), _r("b", "against", ("quiet", False))], "same_axis"),
    ([_r("a", "like", ("quiet", False)), _r("b", "against", ("quiet", True))], "same_axis"),
    ([_r("a", "like", (None, None)), _r("b", "against", ("parking_available", True))], "unclear"),
    ([_r("a", "like", ("quiet", True)), _r("b", "against", ("parking_available", True))], "different_axes"),
    ([_r("a", "like", ("quiet", True)), _r("b", "against", (None, None))], "unclear"),         # 칩 「취향이 아니에요」만
    ([_r("a", "like", ("quiet", True)), _r("b", "against", ("quiet", True))], "unclear"),      # 같은 키, 같은 방향
    ([_r("a", "like", ("quiet", True))], "unclear"),
    ([_r("a", "like", ("quiet", True), ("spacious", True)), _r("b", "against", ("spacious", False))], "same_axis"),
])
def test_compare_reasons_conflict_type(reasons, conflict):
    assert core.compare_reasons(reasons)["conflict_type"] == conflict


def test_compare_reasons_groups_reaction_ids_by_key_and_direction():
    result = core.compare_reasons([
        _r("a", "like", ("quiet", True), (None, None)), _r("c", "like", ("quiet", True)),
        _r("b", "against", ("quiet", False), ("quiet", None)),
    ])

    assert result["keys"] == [{
        "fact_key": "quiet",
        "want": [{"reaction_id": "a", "side": "like"}, {"reaction_id": "c", "side": "like"}],
        "avoid": [{"reaction_id": "b", "side": "against"}],
    }]


def test_render_analysis_uses_labels_and_skips_unknown_keys():
    analysis = core.compare_reasons([
        _r("a", "like", ("quiet", True)), _r("c", "like", ("quiet", True)),
        _r("b", "against", ("quiet", False), ("parking_available", True)),
    ])

    rendered = core.render_analysis(analysis, {"quiet": "조용한 곳"})

    assert rendered.conflict_type == "same_axis"
    assert [(a.label, a.like_side, a.against_side) for a in rendered.axes] == [("조용한 곳", "원함 2", "원하지 않음 1")]
    assert core.render_analysis(None, {}) is None


# ---------------------------------------------------------------- 사용량 합치기 (#564)

def test_model_usage_sums_tokens_and_joins_distinct_names_in_call_order():
    priority = AgentUsage(model="gpt-6-luna", prompt_version="prioritize-v1", tokens_in=100, tokens_out=10)
    diagnosis = AgentUsage(model="gpt-6-luna", prompt_version="diagnose-v1", tokens_in=300, tokens_out=40)

    assert core.model_usage([priority, diagnosis]) == {
        "model": "gpt-6-luna", "prompt_version": "prioritize-v1+diagnose-v1", "tokens_in": 400, "tokens_out": 50,
    }


def test_model_usage_without_calls_or_with_stubs_is_empty():
    empty = {"model": None, "prompt_version": None, "tokens_in": 0, "tokens_out": 0}
    assert core.model_usage([]) == empty
    assert core.model_usage([AgentUsage(), AgentUsage()]) == empty

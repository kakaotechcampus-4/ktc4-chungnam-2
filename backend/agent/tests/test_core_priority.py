"""우선순위 코드 규칙(명세 7절, #582), 충돌 종류(6.3) — 순수 함수."""

from dataclasses import replace

import pytest

from agent import core
from agent.schemas import AgentUsage
from agent.tests.snaps import NOW

POLICY = core.parse_policy({
    "version": 2, "rules": {"urgent_dday": 3},
    "weights": {"stall": 3, "split": 3, "category_gap": 2, "no_reaction": 1},
})


def _sig(sid, diagnosis, category=None, *, ratio=None, affected=1, dday=30, dismissals=0):
    sig = core.make_signal(diagnosis, category=category, evidence=[(f"{sid}-e", "pin", NOW)], features={
        "elapsed_ratio": ratio, "affected_members": affected, "dday": dday, "recent_dismissals": dismissals,
    })
    return replace(sig, id=sid)


def _ids(signals):
    return [s.id for s in signals]


def _rank(*signals, policy=POLICY):
    order, hits = core.rank_signals(list(signals), policy)
    return _ids(order), hits


# ---------------------------------------------------------------- 기본 순서

def test_base_order_is_weights_then_detection_order_without_hits():
    gap, unseen, stall, split = (_sig("s1", "category_gap", "카페"), _sig("s2", "no_reaction"),
                                 _sig("s3", "stall", "음식점"), _sig("s4", "split", "카페"))

    assert _rank(gap, unseen, stall, split) == (["s3", "s4", "s1", "s2"], [])


# ---------------------------------------------------------------- 출발 임박 (urgent_dday)

@pytest.mark.parametrize("dday, first, hits", [
    (30, "s1", []),
    (4, "s1", []),
    (3, "s2", ["urgent_dday"]),     # 3일 이내부터
    (0, "s2", ["urgent_dday"]),
    (-1, "s2", ["urgent_dday"]),    # 여행 중
])
def test_urgent_dday_moves_category_gap_first(dday, first, hits):
    stall = _sig("s1", "stall", "음식점", ratio=3.0, affected=3, dday=dday)
    gap = _sig("s2", "category_gap", "카페", affected=3, dday=dday)

    order, rule_hits = _rank(stall, gap)

    assert (order[0], rule_hits) == (first, hits)


def test_urgent_gaps_keep_their_order_and_the_rest_follows():
    gap_cafe = _sig("s1", "category_gap", "카페", affected=3, dday=2)
    gap_sight = _sig("s2", "category_gap", "관광지", affected=3, dday=2)
    stall = _sig("s3", "stall", "음식점", ratio=2.0, dday=2)
    unseen = _sig("s4", "no_reaction", affected=3, dday=2)

    assert _rank(unseen, stall, gap_cafe, gap_sight) == (["s1", "s2", "s3", "s4"], ["urgent_dday"])


# ---------------------------------------------------------------- 같은 weight: 영향 인원, 경과 비율

def test_same_weight_more_affected_members_first():
    stall = _sig("s1", "stall", "음식점", ratio=5.0, affected=1)
    split = _sig("s2", "split", "음식점", ratio=1.0, affected=3)

    assert _rank(stall, split) == (["s2", "s1"], ["affected_members"])


def test_affected_members_does_not_cross_weights():
    unseen = _sig("s1", "no_reaction", affected=4)
    stall = _sig("s2", "stall", "음식점", affected=1)

    assert _rank(unseen, stall) == (["s2", "s1"], [])


def test_same_weight_and_affected_then_elapsed_ratio_with_none_last():
    a = _sig("s1", "stall", "카페", ratio=None, affected=2)
    b = _sig("s2", "split", "음식점", ratio=1.2, affected=2)
    c = _sig("s3", "stall", "음식점", ratio=2.5, affected=2)

    assert _rank(a, b, c) == (["s3", "s2", "s1"], ["elapsed_ratio"])


# ---------------------------------------------------------------- 연속 닫힘 (recent_dismissals)

def test_dismissed_signal_goes_after_undismissed_of_same_weight():
    stall = _sig("s1", "stall", "음식점", ratio=4.0, affected=3, dismissals=2)
    split = _sig("s2", "split", "카페", ratio=1.0, affected=2)

    assert _rank(stall, split) == (["s2", "s1"], ["recent_dismissals"])


def test_dismissed_signal_stays_ahead_of_lower_weight():
    stall = _sig("s1", "stall", "음식점", dismissals=1)
    gap = _sig("s2", "category_gap", "카페", affected=3)

    assert _rank(gap, stall) == (["s1", "s2"], [])   # 같은 weight 안에서만 뒤로


def test_dismissals_outrank_affected_members_and_both_hits_are_recorded():
    a = _sig("s1", "stall", "음식점", affected=3, dismissals=1)
    b = _sig("s2", "split", "카페", affected=1)
    c = _sig("s3", "split", "음식점", affected=2)

    assert _rank(a, b, c) == (["s3", "s2", "s1"], ["recent_dismissals", "affected_members"])


# ---------------------------------------------------------------- always_first, never_first

def test_always_first():
    policy = replace(POLICY, always_first=("no_reaction",))
    stall = _sig("s1", "stall", "음식점")
    unseen = _sig("s2", "no_reaction")

    assert _rank(stall, unseen, policy=policy) == (["s2", "s1"], ["always_first"])
    assert _rank(unseen, policy=policy) == (["s2"], [])


def test_always_first_beats_urgent_dday():
    policy = replace(POLICY, always_first=("stall",))
    stall = _sig("s1", "stall", "음식점", dday=1)
    gap = _sig("s2", "category_gap", "카페", dday=1)

    assert _rank(stall, gap, policy=policy) == (["s1", "s2"], ["urgent_dday", "always_first"])


def test_never_first_promotes_first_allowed_signal():
    policy = replace(POLICY, never_first=("stall", "split"))
    stall = _sig("s1", "stall", "음식점")
    split = _sig("s2", "split", "카페")
    unseen = _sig("s3", "no_reaction")
    gap = _sig("s4", "category_gap", "카페")

    assert _rank(stall, split, unseen, gap, policy=policy) == (["s4", "s1", "s2", "s3"], ["never_first"])


def test_never_first_without_alternative_keeps_order():
    policy = replace(POLICY, never_first=("no_reaction",))

    assert _rank(_sig("s1", "no_reaction"), policy=policy) == (["s1"], [])


def test_signals_without_features_use_defaults():
    """features가 비어도(테스트용 신호) 기본 순서로 정해진다 — 영향 인원 0, 닫힘 0, 경과 비율과 dday 없음."""
    gap = replace(core.make_signal("category_gap", category="카페", evidence=[], features={}), id="s1")
    stall = replace(core.make_signal("stall", category="음식점", evidence=[], features={}), id="s2")

    assert _rank(gap, stall) == (["s2", "s1"], [])


# ---------------------------------------------------------------- choose_top 기록

def test_choose_top_records_rules_and_rule_hits():
    stall = _sig("s1", "stall", "음식점", affected=1)
    split = _sig("s2", "split", "음식점", affected=3)
    unseen = _sig("s3", "no_reaction")

    top, log = core.choose_top([stall, split, unseen], POLICY)

    assert top.id == "s2"
    assert log == {
        "source": "rules", "final_order": ["s2", "s1", "s3"],
        "fingerprints": [split.fingerprint, stall.fingerprint, unseen.fingerprint], "rule_hits": ["affected_members"],
    }


def test_choose_top_single_and_none():
    stall = _sig("s1", "stall", "음식점")

    top, log = core.choose_top([stall], POLICY)

    assert (top.id, log) == ("s1", {"source": "single", "final_order": ["s1"], "fingerprints": [stall.fingerprint],
                                    "rule_hits": []})
    assert core.choose_top([], POLICY) == (None, None)


def test_fallback_order_is_rank_signals_order():
    signals = [_sig("s1", "category_gap", "카페", dday=1), _sig("s2", "stall", "음식점", dday=1)]

    assert _ids(core.fallback_order(signals, POLICY)) == _ids(core.rank_signals(signals, POLICY)[0]) == ["s1", "s2"]


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

def test_model_usage_is_the_diagnosis_call():
    diagnosis = AgentUsage(model="gpt-6-luna", prompt_version="diagnose-v2", tokens_in=300, tokens_out=40)

    assert core.model_usage([diagnosis]) == {
        "model": "gpt-6-luna", "prompt_version": "diagnose-v2", "tokens_in": 300, "tokens_out": 40,
    }


def test_model_usage_without_calls_or_with_stubs_is_empty():
    empty = {"model": None, "prompt_version": None, "tokens_in": 0, "tokens_out": 0}
    assert core.model_usage([]) == empty
    assert core.model_usage([AgentUsage(), AgentUsage()]) == empty

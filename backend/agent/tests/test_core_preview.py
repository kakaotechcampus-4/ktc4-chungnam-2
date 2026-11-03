"""미리 돌려 보기와 절충안(명세 6.7, #1180)의 순수 함수 — 무엇을 돌리나(preview_target, compromise_keys), 진단 입력에 넣는 칸
(preview_input, diagnosis_input), 검증 6단계(미리 돌려 본 수가 0이면 open_recommend를 뺀다)."""

import json

from agent import core
from agent.tests.test_core_verify import (
    C_AGAINST, C_LIKE, C_REF, C_TOOL, GOOD_ACTIONS, NAMES, SNAP, SPLIT, STALL, TOOLS, _out, _removed,
)

DIFFERENT = {"conflict_type": "different_axes", "keys": [
    {"fact_key": "parking_available", "want": [{"reaction_id": "r3", "side": "against"}], "avoid": []},
    {"fact_key": "quiet", "want": [{"reaction_id": "r1", "side": "like"}], "avoid": []},
    {"fact_key": "spicy_focused", "want": [], "avoid": [{"reaction_id": "r1", "side": "like"}]},
]}
PREVIEW = {"passed_count": 4, "with_keys_count": 1, "with_labels": ["조용한 곳"],
           "funnel": [{"key": "pool", "removed_count": 0}, {"key": "radius", "removed_count": 2}]}
C_PREVIEW = {"id": "c6", "kind": "tool_result", "call_id": "p1", "path": "passed_count", "value": 4}


def test_compromise_keys_are_the_keys_the_like_side_wanted():
    """🚫 쪽 조건은 근거 줄로 이미 들어간다. ♥ 쪽이 피한 키(spicy_focused 피함)는 「갖춘 곳」으로 셀 수 없어 넣지 않는다."""
    assert core.compromise_keys(DIFFERENT) == ["quiet"]
    assert core.compromise_keys(None) == []


def test_preview_runs_for_a_stall_and_a_split_on_different_axes_only():
    assert core.preview_target(STALL, None) == ("음식점", [])
    assert core.preview_target(SPLIT, DIFFERENT) == ("음식점", ["quiet"])
    for conflict in ("same_axis", "unclear"):   # 같은 특징을 반대로 원하면 둘 다 만족하는 곳이 정의상 없다
        assert core.preview_target(SPLIT, {"conflict_type": conflict, "keys": DIFFERENT["keys"]}) is None
    assert core.preview_target(SPLIT, None) is None   # ② 실패로 비교가 없다


def test_diagnosis_input_carries_counts_and_labels_but_not_the_funnel():
    stall = core.diagnosis_input(STALL, SNAP, None, {"passed_count": 0, "funnel": []})
    split = core.diagnosis_input(SPLIT, SNAP, DIFFERENT, PREVIEW)

    assert stall["preview"] == {"passed_count": 0}
    assert split["preview"] == {"passed_count": 4, "with_keys_count": 1, "with_labels": ["조용한 곳"]}
    assert core.diagnosis_input(SPLIT, SNAP, DIFFERENT)["preview"] is None   # 돌리지 못했으면 null
    assert "funnel" not in json.dumps([stall, split])


def _stall_out(actions, claims=None):
    return _out(
        diagnosis="stall", claims=claims or [C_TOOL, C_REF],
        advice=[{"text": "반대 의견을 반영해 다시 추천받아 볼 수 있어요", "basis": ["c5"], "is_guess": True}],
        actions=actions,
    )


OPEN = {"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c5"]}
SHOW = {"type": "show_pins", "category": None, "pin_ids": ["p1"], "basis": ["c4"]}


def test_open_recommend_is_dropped_when_the_preview_found_nothing():
    v = core.verify_diagnosis(_stall_out([OPEN, SHOW]), STALL, SNAP, TOOLS, member_names=NAMES,
                              preview={"passed_count": 0, "funnel": []})

    assert v.outcome == "suggested"
    assert [a["type"] for a in v.draft.actions] == ["show_pins"]
    assert _removed(v, "actions") == {0: "preview_empty"}


def test_a_lone_open_recommend_dropped_for_zero_leaves_the_sentence():
    """행동이 다 빠져도 문장이 남으면 제안은 성립한다(7단계). 문장도 없으면 침묵이다."""
    kept = core.verify_diagnosis(_stall_out([OPEN]), STALL, SNAP, TOOLS, member_names=NAMES,
                                 preview={"passed_count": 0})
    silent = core.verify_diagnosis(
        _out(diagnosis="stall", claims=[C_TOOL], advice=[], actions=[OPEN]), STALL, SNAP, TOOLS,
        member_names=NAMES, preview={"passed_count": 0},
    )

    assert kept.outcome == "suggested" and kept.draft.actions == []
    assert (silent.outcome, silent.record["failed_step"]) == ("invalid_claims", 7)


def test_open_recommend_stays_when_places_remain_or_the_preview_did_not_run():
    for preview in ({"passed_count": 3}, None):   # None — ②가 실패해 미리 돌려 보지 못했다(검사를 건너뛴다)
        v = core.verify_diagnosis(_stall_out([OPEN]), STALL, SNAP, TOOLS, member_names=NAMES, preview=preview)
        assert [a["type"] for a in v.draft.actions] == ["open_recommend"]


def test_split_open_recommend_follows_the_same_rule():
    tools = {**TOOLS, "p1": PREVIEW | {"passed_count": 0}}
    v = core.verify_diagnosis(_out(), SPLIT, SNAP, tools, member_names=NAMES, comparison=DIFFERENT,
                              preview=tools["p1"])

    assert v.draft.actions == [] and _removed(v, "actions") == {0: "preview_empty"}
    assert GOOD_ACTIONS[0]["type"] == "open_recommend"


def test_the_preview_count_is_checked_like_any_tool_result():
    """모델은 수를 p1의 ToolClaim으로만 쓴다(11.2 3단계). 값이 다르면 claim과 그 claim에 기댄 문장이 빠진다."""
    tools = {**TOOLS, "p1": PREVIEW}
    line = {"text": "두 의견을 다 맞추는 곳이 {c6.value}곳 있어요", "basis": ["c6"], "is_guess": False}
    right = _out(claims=[C_LIKE, C_AGAINST, C_PREVIEW | {"path": "with_keys_count", "value": 1}], advice=[line])
    wrong = _out(claims=[C_LIKE, C_AGAINST, C_PREVIEW | {"value": 5}], advice=[line])

    ok = core.verify_diagnosis(right, SPLIT, SNAP, tools, member_names=NAMES, comparison=DIFFERENT, preview=PREVIEW)
    bad = core.verify_diagnosis(wrong, SPLIT, SNAP, tools, member_names=NAMES, comparison=DIFFERENT, preview=PREVIEW)

    assert ok.draft.advice == [{"slot_text": line["text"], "is_guess": False}]
    assert _removed(bad, "claims") == {"c6": "tool_mismatch"} and _removed(bad, "lines") == {0: "basis"}

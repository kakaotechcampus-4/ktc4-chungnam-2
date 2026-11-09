"""미리 돌려 보기와 절충안(명세 6.7, #1180)의 순수 함수 — 무엇을 돌리나(preview_target, compromise_conditions), 진단 입력에 넣는 칸
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
PREVIEW = {"passed_count": 4, "both_sides_count": 3, "both_sides_confirmed_count": 1,
           "like_labels": ["조용한 곳", "매운맛 전문 제외"], "against_labels": ["주차 가능"],
           "funnel": [{"key": "pool", "removed_count": 0}, {"key": "radius", "removed_count": 2}]}
C_PREVIEW = {"id": "c6", "kind": "tool_result", "call_id": "p1", "path": "passed_count", "value": 4}


LIKE_QUIET = {"fact_key": "quiet", "wants": True, "side": "like"}
LIKE_NOT_SPICY = {"fact_key": "spicy_focused", "wants": False, "side": "like"}
AGAINST_PARKING = {"fact_key": "parking_available", "wants": True, "side": "against"}


def test_compromise_conditions_take_both_sides_with_their_direction():
    """#1253 뒤 🚫 사유는 거르지 않아 🚫 쪽 조건(주차)도 센다(#1600). ♥ 쪽 피함(맵지 않음)도 방향과 함께 들어간다.
    순서는 ♥ 원함, ♥ 피함, 🚫 원함, 🚫 피함이고 그 안은 키 순서다."""
    assert core.compromise_conditions(DIFFERENT) == [LIKE_QUIET, LIKE_NOT_SPICY, AGAINST_PARKING]
    assert core.compromise_conditions(None) == []


def test_compromise_conditions_keep_one_of_each_and_skip_keys_without_a_side():
    twice = {"conflict_type": "different_axes", "keys": [
        {"fact_key": "quiet", "want": [{"reaction_id": "r1", "side": "like"}, {"reaction_id": "r2", "side": "like"}], "avoid": []},
        {"fact_key": "wait_short", "want": [{"reaction_id": "r3", "side": "against"}],
         "avoid": [{"reaction_id": "r4", "side": "against"}]},
    ]}

    assert core.compromise_conditions(twice) == [
        LIKE_QUIET, {"fact_key": "wait_short", "wants": True, "side": "against"},
        {"fact_key": "wait_short", "wants": False, "side": "against"},
    ]


def test_condition_labels_split_by_side_and_mark_avoided_ones():
    labels = {"quiet": "조용한 곳", "spicy_focused": "매운맛 전문", "parking_available": "주차 가능"}

    assert core.condition_labels([LIKE_QUIET, LIKE_NOT_SPICY, AGAINST_PARKING], labels) == {
        "like_labels": ["조용한 곳", "매운맛 전문 제외"], "against_labels": ["주차 가능"],
    }
    assert core.condition_labels([LIKE_QUIET | {"fact_key": "unknown_key"}], labels) == {"like_labels": [], "against_labels": []}


def test_preview_runs_for_a_stall_and_every_split_with_a_comparison():
    """split은 충돌 종류와 상관없이 돌린다(#1317). 양쪽 조건을 더하는 것은 different_axes뿐이다 — same_axis·unclear는 두 쪽을
    다 맞추는 곳이 없거나 알 수 없어 추천에 남는 수만 센다."""
    assert core.preview_target(STALL, None) == ("음식점", [])
    assert core.preview_target(SPLIT, DIFFERENT) == ("음식점", [LIKE_QUIET, LIKE_NOT_SPICY, AGAINST_PARKING])
    for conflict in ("same_axis", "unclear"):
        assert core.preview_target(SPLIT, {"conflict_type": conflict, "keys": DIFFERENT["keys"]}) == ("음식점", [])
    assert core.preview_target(SPLIT, None) is None   # ② 실패로 비교가 없다


def test_diagnosis_input_carries_counts_and_labels_but_not_the_funnel():
    stall = core.diagnosis_input(STALL, SNAP, None, {"passed_count": 0, "funnel": []})
    split = core.diagnosis_input(SPLIT, SNAP, DIFFERENT, PREVIEW)

    assert stall["preview"] == {"passed_count": 0}
    assert split["preview"] == {k: v for k, v in PREVIEW.items() if k != "funnel"}
    assert core.diagnosis_input(SPLIT, SNAP, DIFFERENT)["preview"] is None   # 돌리지 못했으면 null
    assert "funnel" not in json.dumps([stall, split])


def _stall_out(actions, claims=None):
    return _out(
        diagnosis="stall", claims=claims or [C_TOOL, C_REF],
        advice=[{"text": "반대 의견을 반영해 다시 추천받아 볼 수 있어요", "basis": ["c5"], "is_guess": True}],
        actions=actions,
    )


OPEN = {"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c5"]}
SEARCH = {"type": "search_place", "category": "음식점", "pin_ids": None, "basis": ["c5"]}
SHOW = {"type": "show_pins", "category": None, "pin_ids": ["p1"], "basis": ["c4"]}


def test_open_recommend_is_dropped_when_the_preview_found_nothing():
    v = core.verify_diagnosis(_stall_out([OPEN, SEARCH]), STALL, SNAP, TOOLS, member_names=NAMES,
                              preview={"passed_count": 0, "funnel": []})

    assert v.outcome == "suggested"
    assert [(a["type"], a["label"]) for a in v.draft.actions] == [("search_place", "음식점 검색")]
    assert _removed(v, "actions") == {0: "preview_empty"}


def test_show_pins_from_the_model_is_dropped_for_both_types():
    """모델 유형의 허용 버튼에 「핀 보기」가 없다(#1317). 정체·갈림 모두 추천 받기와 장소 검색만 남는다."""
    stall = core.verify_diagnosis(_stall_out([SHOW, OPEN]), STALL, SNAP, TOOLS, member_names=NAMES)
    split = core.verify_diagnosis(_out(actions=[SHOW, SEARCH | {"basis": ["c1"]}, SEARCH | {"basis": ["c1"], "category": "카페"}]),
                                  SPLIT, SNAP, TOOLS, member_names=NAMES, comparison=DIFFERENT)

    assert [a["type"] for a in stall.draft.actions] == ["open_recommend"] and _removed(stall, "actions") == {0: "type"}
    assert [(a["type"], a["label"]) for a in split.draft.actions] == [("search_place", "음식점 검색")]
    assert _removed(split, "actions") == {0: "type", 2: "category"}   # split의 검색은 그 핀의 카테고리만


def test_same_axis_split_previews_and_drops_recommend_at_zero():
    """same_axis 갈림도 미리 센 수가 0이면 「추천 받기」가 빠지고 장소 검색이 남는다."""
    same = {"conflict_type": "same_axis", "keys": DIFFERENT["keys"]}
    zero = {"passed_count": 0, "funnel": []}
    actions = [GOOD_ACTIONS[0], SEARCH | {"basis": GOOD_ACTIONS[0]["basis"]}]
    v = core.verify_diagnosis(_out(actions=actions), SPLIT, SNAP, {**TOOLS, "p1": zero}, member_names=NAMES,
                              comparison=same, preview=zero)

    assert core.preview_target(SPLIT, same) == ("음식점", [])
    assert [a["type"] for a in v.draft.actions] == ["search_place"] and _removed(v, "actions") == {0: "preview_empty"}


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
    line = {"text": "두 의견에 어긋나지 않는 곳이 {c6.value}곳 있어요", "basis": ["c6"], "is_guess": False}
    right = _out(claims=[C_LIKE, C_AGAINST, C_PREVIEW | {"path": "both_sides_count", "value": 3}], advice=[line])
    wrong = _out(claims=[C_LIKE, C_AGAINST, C_PREVIEW | {"value": 5}], advice=[line])

    ok = core.verify_diagnosis(right, SPLIT, SNAP, tools, member_names=NAMES, comparison=DIFFERENT, preview=PREVIEW)
    bad = core.verify_diagnosis(wrong, SPLIT, SNAP, tools, member_names=NAMES, comparison=DIFFERENT, preview=PREVIEW)

    assert ok.draft.advice == [{"slot_text": line["text"], "is_guess": False}]
    assert _removed(bad, "claims") == {"c6": "tool_mismatch"} and _removed(bad, "lines") == {0: "basis"}

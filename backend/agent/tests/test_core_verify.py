"""모델 진단 출력 검증(명세 11.2)과 진단 입력 — 순수 함수(#533). 17절 3번(검증)과 2번의 진단 부분.

단계마다 통과 예와 실패 예를 둔다. 스냅샷: 음식점 핀 p1(u1이 찍음)에 u1 ♥(사유 있음), u2 ♥, u3 🚫(사유 있음).
"""

import json
from dataclasses import replace

import pytest

from agent import core
from agent.schemas import DiagnosisOutput
from agent.tests.snaps import NOW, hours, pin, react, reason, snap

LIKE_TEXT = "분위기가 아늑해서 오래 머물기 좋아요"
AGAINST_TEXT = "주차할 곳이 전혀 없어서 차로 가기 힘들어요"

R1 = react("r1", "p1", "u1", "like", NOW - hours(30))
R2 = react("r2", "p1", "u2", "like", NOW - hours(25))
R3 = react("r3", "p1", "u3", "against", NOW - hours(20))
SNAP = snap(
    pins=[pin("p1"), pin("p2", category="카페")], reactions=[R1, R2, R3],
    reasons=[reason(R1, LIKE_TEXT, alias="m1"), reason(R3, AGAINST_TEXT, alias="m3")],
)
SPLIT = replace(core.detect_split(SNAP, NOW, hours(3))[0], id="s1")
STALL = replace(core.make_signal("stall", category="음식점", evidence=[("r3", "against", R3.updated_at)],
                                 features={"trigger": "time"}), id="s1")
TOOLS = {"t1": {"ready": True, "answered_count": 2, "required_count": 1, "reasons": [{"reaction_id": "r3"}]}}
NAMES = ["김민지", "박", "이준호"]

C_LIKE = {"id": "c1", "kind": "count", "subject": "pin", "subject_id": "p1", "metric": "like", "value": 2}
C_AGAINST = {"id": "c2", "kind": "count", "subject": "pin", "subject_id": "p1", "metric": "against", "value": 1}
C_QUOTE = {"id": "c3", "kind": "quote", "reaction_id": "r3", "text": "주차할 곳이  전혀 없어서"}   # 공백 정규화
C_REF = {"id": "c4", "kind": "ref", "object": "pin", "ref_id": "p1"}
C_TOOL = {"id": "c5", "kind": "tool_result", "call_id": "t1", "path": "ready", "value": True}
GOOD_LINES = [
    {"text": "♥ {c1.value}명, 🚫 {c2.value}명으로 갈렸어요", "basis": ["c1", "c2"], "is_guess": False},
    {"text": "🚫 쪽은 {c3}라고 했어요", "basis": ["c3"], "is_guess": False},
    {"text": "주차가 되는 곳을 같이 찾아보면 좋겠어요", "basis": [], "is_guess": True},
]
GOOD_ACTIONS = [{"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c1", "c2"]}]


def _out(*, claims=None, advice=None, actions=None, decision="suggest", signal_id="s1", diagnosis="split"):
    return DiagnosisOutput.model_validate({
        "decision": decision, "diagnosis": diagnosis, "signal_id": signal_id,
        "claims": [C_LIKE, C_AGAINST, C_QUOTE, C_REF, C_TOOL] if claims is None else claims,
        "advice": GOOD_LINES if advice is None else advice,
        "actions": GOOD_ACTIONS if actions is None else actions,
    })


def _verify(out, top=SPLIT, **kw):
    return core.verify_diagnosis(out, top, SNAP, TOOLS, member_names=NAMES, **kw)


def _removed(v, part):
    return {r.get("id", r.get("index")): r["reason"] for r in v.record[part]["removed"]}


# ---------------------------------------------------------------- 통과

def test_valid_split_diagnosis_becomes_slot_draft_without_quote_text():
    comparison = {"conflict_type": "different_axes", "keys": []}

    v = _verify(_out(), comparison=comparison)

    assert v.outcome == "suggested" and v.record["established"] is True
    assert v.draft.title == "의견이 갈린 핀이 있어요"
    assert [a["slot_text"] for a in v.draft.advice] == [line["text"] for line in GOOD_LINES]
    assert v.draft.actions == [{"index": 0, "type": "open_recommend", "label": "음식점 추천 받기",
                                "params": {"category": "음식점"}}]
    assert v.draft.analysis == comparison
    quote = next(c for c in v.draft.claims if c["kind"] == "quote")
    # 대조용 text는 버리고 검증한 범위와 그 범위의 다이제스트만 남긴다(2절 13번, #717)
    span = "주차할 곳이 전혀 없어서"
    assert quote == {"id": "c3", "kind": "quote", "reaction_id": "r3", "start": 0, "end": len(span),
                     "digest": core.quote_digest(span)}
    assert AGAINST_TEXT[quote["start"]:quote["end"]] == span
    assert AGAINST_TEXT[:4] not in json.dumps([v.draft.claims, v.record], ensure_ascii=False)


def test_valid_stall_needs_no_count_claims():
    out = _out(diagnosis="stall", claims=[C_TOOL], advice=[
        {"text": "추천 준비가 됐어요", "basis": ["c5"], "is_guess": False}],
        actions=[{"type": "search_place", "category": None, "pin_ids": None, "basis": ["c5"]}])

    v = _verify(out, top=STALL)

    assert v.outcome == "suggested"
    assert v.draft.title == "음식점 후보가 반대 의견 뒤로 멈춰 있어요"
    assert v.draft.actions[0]["params"] == {"category": "음식점"}   # 비운 카테고리는 신호의 카테고리
    assert v.draft.analysis is None


# ---------------------------------------------------------------- 1단계: decision

@pytest.mark.parametrize("decision", ["silent", "unknown"])
def test_silent_and_unknown_are_kept_as_is(decision):
    v = _verify(_out(decision=decision, claims=[], advice=[], actions=[]))

    assert (v.outcome, v.draft, v.record) == (decision, None, {"decision": decision})


# ---------------------------------------------------------------- 2단계: 진단 성립

@pytest.mark.parametrize("kw", [{"signal_id": "s9"}, {"diagnosis": "stall"}])
def test_other_signal_or_diagnosis_is_invalid_claims(kw):
    v = _verify(_out(**kw))

    assert (v.outcome, v.draft, v.record["failed_step"]) == ("invalid_claims", None, 2)


# ---------------------------------------------------------------- 3단계: claim 대조

def test_made_up_count_is_removed_and_split_loses_required_claim():
    """17절 3번 — 지어낸 count → claim 제거 → 필수 claim 없음 → invalid_claims."""
    v = _verify(_out(claims=[C_LIKE | {"value": 3}, C_AGAINST, C_QUOTE], advice=GOOD_LINES[1:]))

    assert _removed(v, "claims") == {"c1": "count_mismatch"}
    assert (v.outcome, v.record["failed_step"]) == ("invalid_claims", 7)


@pytest.mark.parametrize("claim, reason", [
    (C_QUOTE | {"text": "주차가 편해요"}, "quote_not_found"),                 # 원문에 없는 인용
    (C_QUOTE | {"reaction_id": "r2"}, "quote_not_found"),                    # 사유 글이 없는 반응
    (C_REF | {"ref_id": "p_other_map"}, "ref_not_found"),
    (C_TOOL | {"value": 1}, "tool_mismatch"),                                # True와 1은 다르다
    (C_TOOL | {"path": "missing"}, "tool_mismatch"),
    (C_TOOL | {"call_id": "t9"}, "tool_call_not_found"),
    (C_AGAINST | {"id": "c6", "subject_id": "p_none"}, "count_mismatch"),
    (C_LIKE | {"id": "x1"}, "bad_id"),
])
def test_claim_that_does_not_match_is_removed(claim, reason):
    v = _verify(_out(claims=[C_LIKE, C_AGAINST, claim], advice=GOOD_LINES[:1]))

    assert _removed(v, "claims") == {claim["id"]: reason}
    assert v.outcome == "suggested"   # 남은 claim으로 성립한다


@pytest.mark.parametrize("text, quote, span", [
    ("주차할 곳이 전혀 없어서", "곳이 전혀", (4, 9)),
    ("  주차할 곳이\n\n 전혀 없어요", "곳이 전혀", (6, 13)),   # 범위는 정규화 전 원문 기준(줄바꿈 포함)
    ("가나 가나다", "가나다", (3, 6)),                          # 처음 나오는 곳
    ("가나다", "라", None),
    ("가나다", "", None),
])
def test_quote_span_is_in_original_text(text, quote, span):
    assert core.quote_span(text, quote) == span
    if span:
        assert core._normalize(text[span[0]:span[1]]) == quote


def test_quote_longer_than_the_limit_is_removed():
    """인용은 QUOTE_MAX_CHARS(60)까지다(#717). 범위는 원문 기준으로 잰다."""
    long_text = "가" * 70
    r3 = reason(R3, long_text, alias="m3")
    long_snap = replace(SNAP, reasons=(SNAP.reasons[0], r3))
    ok = C_QUOTE | {"text": "가" * core.QUOTE_MAX_CHARS}
    too_long = C_QUOTE | {"id": "c6", "text": "가" * (core.QUOTE_MAX_CHARS + 1)}

    v = core.verify_diagnosis(_out(claims=[C_LIKE, C_AGAINST, ok, too_long], advice=GOOD_LINES[:2]), SPLIT,
                              long_snap, TOOLS, member_names=NAMES)

    assert _removed(v, "claims") == {"c6": "quote_too_long"}
    [quote] = [c for c in v.draft.claims if c["kind"] == "quote"]
    assert (quote["id"], quote["end"] - quote["start"]) == ("c3", core.QUOTE_MAX_CHARS)


def test_tool_claim_follows_list_path_and_counts_match_other_subjects():
    claims = [
        C_LIKE, C_AGAINST,
        {"id": "c6", "kind": "tool_result", "call_id": "t1", "path": "reasons.0.reaction_id", "value": "r3"},
        {"id": "c7", "kind": "count", "subject": "category", "subject_id": "음식점", "metric": "pins", "value": 1},
        {"id": "c8", "kind": "count", "subject": "map", "subject_id": None, "metric": "unseen", "value": 1},
        {"id": "c9", "kind": "count", "subject": "pin", "subject_id": "p2", "metric": "unseen", "value": 2},
    ]

    v = _verify(_out(claims=claims, advice=GOOD_LINES[:1]))

    assert v.record["claims"]["removed"] == []


def test_duplicate_claim_id_drops_both():
    v = _verify(_out(claims=[C_LIKE, C_AGAINST, C_AGAINST | {"value": 5}], advice=GOOD_LINES[:1]))

    assert _removed(v, "claims") == {"c2": "duplicate_id"}
    assert v.outcome == "invalid_claims"   # 앞의 c2도 믿지 않아 split 필수 claim이 빠진다


# ---------------------------------------------------------------- 5단계: 문장

@pytest.mark.parametrize("line, reason", [
    ({"text": "♥ 2명이 좋아해요", "basis": [], "is_guess": False}, "digit"),                 # 슬롯 밖 숫자
    ({"text": "♥ {c1.value}명 중 3명", "basis": ["c1"], "is_guess": False}, "digit"),
    ({"text": "김민지님은 좋아해요", "basis": [], "is_guess": True}, "member_name"),         # 구성원 표시 이름
    ({"text": "m3은 반대했어요", "basis": [], "is_guess": True}, "member_name"),             # 별칭
    ({"text": "이 핀으로 확정 하세요", "basis": [], "is_guess": True}, "forbidden"),         # 금지 표현(공백 무시)
    ({"text": "여기로 가세요", "basis": [], "is_guess": True}, "forbidden"),
    ({"text": "다들 이 핀으로 결정하라고 해요", "basis": [], "is_guess": True}, "forbidden"),    # 명령형(#534)
    ({"text": "주차할 곳이 전혀 없다고 해요", "basis": [], "is_guess": True}, "copied"),     # 슬롯 밖 원문 옮겨 쓰기
    ({"text": "분위기가아늑해서 좋대요", "basis": [], "is_guess": True}, "copied"),
    ({"text": "{c9.value}명이 반대해요", "basis": [], "is_guess": False}, "slot"),           # 없는 claim 슬롯
    ({"text": "{c1}명이 좋아해요", "basis": ["c1"], "is_guess": False}, "slot"),             # count는 .value만
    ({"text": "{c3.value}라고 했어요", "basis": ["c3"], "is_guess": False}, "slot"),         # quote는 값 슬롯 아님
    ({"text": "{c1.value}명이 {좋아해요", "basis": ["c1"], "is_guess": False}, "slot"),
    ({"text": "좋아하는 사람이 있어요", "basis": ["c9"], "is_guess": False}, "basis"),       # 없는 근거
    ({"text": "   ", "basis": [], "is_guess": True}, "empty_or_long"),
])
def test_bad_sentence_is_removed(line, reason):
    v = _verify(_out(advice=[GOOD_LINES[0], line]))

    assert _removed(v, "lines") == {1: reason}
    assert v.record["lines"]["kept"] == 1 and v.outcome == "suggested"


def test_sentence_basis_on_removed_claim_is_removed():
    v = _verify(_out(claims=[C_LIKE, C_AGAINST, C_QUOTE | {"text": "없는 말"}]))

    assert _removed(v, "lines") == {1: "basis"}   # 🚫 쪽은 {c3}… — c3가 제거됐다


def test_one_letter_name_is_not_matched():
    """한 글자 이름("박")은 보통 낱말과 겹쳐 보지 않는다."""
    v = _verify(_out(advice=[{"text": "박물관 같은 분위기래요", "basis": [], "is_guess": True}]))

    assert v.record["lines"]["removed"] == []


# ---------------------------------------------------------------- 6단계: 행동

@pytest.mark.parametrize("action, reason", [
    ({"type": "search_place", "category": "음식점", "pin_ids": None, "basis": ["c1"]}, "type"),   # split에 없음
    ({"type": "open_evidence", "category": None, "pin_ids": None, "basis": ["c1"]}, "type"),
    ({"type": "open_recommend", "category": "숙소", "pin_ids": None, "basis": ["c1"]}, "category"),
    ({"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": []}, "basis"),
    ({"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c9"]}, "basis"),
    ({"type": "show_pins", "category": None, "pin_ids": ["p1", "p_gone"], "basis": ["c4"]}, "pin"),
])
def test_disallowed_action_is_removed(action, reason):
    v = _verify(_out(actions=[GOOD_ACTIONS[0], action]))

    assert _removed(v, "actions") == {1: reason}
    assert v.record["actions"]["kept"] == 1


def test_show_pins_label_and_duplicates():
    actions = [{"type": "show_pins", "category": None, "pin_ids": ["p1", "p1"], "basis": ["c4"]}] * 2

    v = _verify(_out(actions=actions))

    assert v.draft.actions == [{"index": 0, "type": "show_pins", "label": "핀 보기", "params": {"pin_ids": ["p1"]}}]


# ---------------------------------------------------------------- 7단계: 성립

def test_nothing_left_is_invalid_claims():
    v = _verify(_out(advice=[{"text": "2명", "basis": [], "is_guess": False}], actions=[]))

    assert (v.outcome, v.draft, v.record["failed_step"], v.record["established"]) == (
        "invalid_claims", None, 7, False)


def test_actions_alone_establish_suggestion():
    v = _verify(_out(advice=[]))

    assert v.outcome == "suggested" and v.draft.advice == []


# ---------------------------------------------------------------- 진단 입력 (17절 1번의 diagnosis_input 부분)

def test_diagnosis_input_has_ids_and_features_only():
    with_run = replace(SNAP, last_run_at={"음식점": NOW - hours(1)})
    comparison = {"conflict_type": "unclear", "keys": []}

    split = core.diagnosis_input(SPLIT, with_run, comparison)
    stall = core.diagnosis_input(STALL, with_run)

    assert split["pin_id"] == "p1" and split["reaction_ids"] == ["r1", "r2", "r3"]
    assert split["comparison"] == comparison and split["category"] == "음식점"
    assert split["place_id"] == "place_p1" and split["counts"] == {"like": 2, "against": 1}   # 필수 claim 값(#534)
    assert stall["against_reaction_ids"] == ["r3"] and stall["against_pin_ids"] == ["p1"] and "pin_id" not in stall
    dumped = json.dumps([split, stall], ensure_ascii=False, default=str)
    for leaked in ("u1", "u2", "u3", LIKE_TEXT, AGAINST_TEXT, "last_run"):
        assert leaked not in dumped


def test_failed_outcome_mapping():
    assert [core.failed_outcome(r) for r in ("invalid_schema", "timeout", "call_failed")] == [
        "invalid_schema", "model_failed", "model_failed"]

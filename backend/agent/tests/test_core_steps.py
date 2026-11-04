"""작업 기록(core.render_steps, 명세 11.3)과 살펴본 상태(core.observation_notice, agent_state, 21.3) — #1297.

작업 기록은 agent_runs 행의 기록과 제안의 facts로 렌더 때 만든다. 문장은 고정 문구와 기록의 숫자뿐이고 사유 글, 핀·장소 이름,
별칭, URL은 기록에 들어 있어도 나가지 않는다(2절 11·13번, 17절 1번에 더함)."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent import core
from agent.schemas import AgentSettings

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
REASON_TEXT = "너무 매워서 못 먹겠어요"
PIN_NAME = "성수 칼국수"
URL = "https://example.com/menu"


def _signal(sid="s1", diagnosis="stall", category="음식점", evidence=("r1", "r2"), fingerprint="fp1", affected=2):
    return {"id": sid, "diagnosis": diagnosis, "category": category, "pin_id": None, "evidence_ids": list(evidence),
            "features": {"affected_members": affected}, "fingerprint": fingerprint, "evidence_hash": "h"}


def _run(signals=None, priority=None, tool_calls=(), verification=None):
    signals = signals if signals is not None else [_signal()]
    priority = priority if priority is not None else {"source": "single", "final_order": ["s1"]}
    return SimpleNamespace(signals=signals, priority=priority, tool_calls=list(tool_calls), verification=verification)


def _sug(fingerprint="fp1", facts=()):
    return SimpleNamespace(fingerprint=fingerprint, facts=list(facts))


def _call(call_id, name, result, args=None):
    return {"call_id": call_id, "name": name, "args": args or {}, "result": result, "ms": 3}


# 실제 정체 진단 한 번의 기록 모양 — 미리 찾기(p1)가 먼저, 모델 도구(t1 …), 웹 확인(w1)이 뒤. 결과에는 저장된 그대로 핀 이름,
# 별칭, 글자 수가 있다
STALL_CALLS = [
    _call("p1", "preview_filter", {"passed_count": 12, "funnel": {"radius": 40}}, {"category": "음식점", "with_keys": []}),
    _call("t1", "get_reasons", {"reasons": [
        {"reaction_id": "r1", "pin_id": "p1", "type": "against", "text_len": 11, "member_alias": "m2"},
        {"reaction_id": "r2", "pin_id": "p2", "type": "against", "text_len": 9, "member_alias": "m3"},
    ], "total": 2}, {"category": "음식점", "types": ["against"]}),
    _call("t2", "get_readiness", {"category": "음식점", "ready": True, "answered_count": 3, "required_count": 3}),
    _call("w1", "web_check", {"status": "found", "statements": 2, "reused": False, "dropped": [], "web_searches": 1},
          {"pin_id": "p1", "fact_key": "parking"}),
]
STALL_VERIFICATION = {
    "decision": "suggest", "signal": True, "claims": {"kept": ["c1", "c2", "c3", "c4"], "removed": []},
    "structure": "skipped", "lines": {"kept": 2, "removed": [{"index": 2, "reason": "number_outside_slot"}]},
    "actions": {"kept": 1, "removed": []}, "established": True,
}
FACTS = [{"pin_id": "p1", "fact_key": "parking"}, {"pin_id": "p2", "fact_key": "quiet"}]


def test_stall_run_renders_every_stage_in_order_with_numbers_from_the_record():
    run = _run(tool_calls=STALL_CALLS, verification=STALL_VERIFICATION)

    steps = core.render_steps(run, _sug(facts=FACTS))

    assert [(s.stage, s.role, s.by, s.by_detail, s.text) for s in steps] == [
        ("감지", "계산", "code", None, "음식점에 반대 의견 2개가 남은 뒤로 새 후보가 없어요"),
        ("조사", "지휘", "ai", None, "반대 사유 2개를 읽었어요"),
        ("조사", "지휘", "ai", None, "추천 준비를 확인했어요"),
        ("미리 찾기", "계산", "code", None, "지금 조건으로 미리 찾아봤어요 · 12곳 남아요"),
        ("우리 데이터", "검증", "code", None, "가게 정보 2개를 우리 데이터에서 확인했어요"),
        ("웹 확인", "검증", "ai", "모델 → 코드", "웹에서 찾아봤어요 · 출처 2개"),
        ("검증", "검증", "code", None, "숫자와 인용 4개를 지도와 대조했어요 · 문장 1개는 뺐어요"),
        ("재확인", "검증", "code", None, core.STEP_RECHECK),
    ]


def test_ranking_appears_only_when_rules_chose_among_several_signals():
    signals = [_signal("s1", "category_gap", "카페", ("p1", "p2"), "fp-gap"), _signal("s2", fingerprint="fp-stall")]
    run = _run(signals=signals, priority={"source": "rules", "final_order": ["s1", "s2"], "rule_hits": []})

    steps = core.render_steps(run, _sug(fingerprint="fp-gap"))

    assert [(s.stage, s.text) for s in steps] == [
        ("감지", "확정한 2곳 중 카페가 없어요"),
        ("순위", "살펴볼 곳 2개 중 이것부터 골랐어요"),
        ("재확인", core.STEP_RECHECK),
    ]


@pytest.mark.parametrize("diagnosis, category, evidence, affected, text", [
    ("no_reaction", None, ("p1", "p2", "p3"), 2, "아직 확인되지 않은 핀이 3개 있어요"),
    ("category_gap", "음식점", ("p1", "p2", "p3"), 3, "확정한 3곳 중 음식점이 없어요"),
    ("split", "카페", ("r1", "r2", "r3"), 3, "카페 핀 하나에서 3명의 의견이 ♥와 🚫로 갈렸어요"),
])
def test_detection_text_per_diagnosis(diagnosis, category, evidence, affected, text):
    run = _run(signals=[_signal(diagnosis=diagnosis, category=category, evidence=evidence, affected=affected)])

    steps = core.render_steps(run, _sug())

    assert [s.stage for s in steps] == ["감지", "재확인"]   # 코드 유형은 도구와 검증이 없다
    assert steps[0].text == text


@pytest.mark.parametrize("name, result, args, text", [
    ("get_map_overview", {"dday": 3, "member_count": 3, "categories": [{"category": "음식점", "pins": 4, "confirmed": 0},
                                                                         {"category": "카페", "pins": 2, "confirmed": 1}]},
     {}, "지도 현황을 봤어요 · 핀 6개"),
    ("get_activity", {"since": None, "counts": {"pin": 1}}, {}, "최근 활동을 봤어요"),
    ("get_reaction_matrix", {"category": "카페", "members": ["m1"], "pins": [{"pin_id": "p1", "name": PIN_NAME}],
                             "total": 1}, {"category": "카페"}, "핀 1개의 반응 표를 봤어요"),
    ("get_reasons", {"reasons": [{"reaction_id": "r1"}], "total": 1}, {"types": ["like"]}, "좋음 사유 1개를 읽었어요"),
    ("get_reasons", {"reasons": [{"reaction_id": "r1"}, {"reaction_id": "r2"}], "total": 2}, {}, "사유 2개를 읽었어요"),
    ("structure_reasons", {"reasons": [{"reaction_id": "r1"}] * 3, "total": 3, "not_found": []}, {},
     "사유 3개를 조건으로 나눠 봤어요"),
    ("compare_reasons", {"pin_id": "p1", "conflict_type": "same_axis", "keys": [], "total": 0}, {},
     "♥ 쪽과 🚫 쪽 조건을 견줘 봤어요"),
    ("get_place_facts", {"facts": [{"place_id": "x", "fact_key": "quiet"}] * 2, "total": 2, "not_found": []}, {},
     "장소 정보 2개를 우리 데이터에서 읽었어요"),
    ("get_readiness", {"category": "음식점", "ready": False, "answered_count": 1, "required_count": 3}, {},
     "추천 준비를 확인했어요"),
    ("new_tool", {"anything": 1}, {}, "지도 데이터를 읽었어요"),
])
def test_one_line_per_model_tool_call_with_a_phrase_per_tool(name, result, args, text):
    run = _run(tool_calls=[_call("t1", name, result, args)])

    tool_steps = [s for s in core.render_steps(run, _sug()) if s.stage == "조사"]

    assert [(s.role, s.by, s.text) for s in tool_steps] == [("지휘", "ai", text)]


def test_every_tool_the_model_can_pick_has_a_phrase():
    from llm import api as llm_api

    allowed = {name for names in llm_api.DIAGNOSIS_TOOLS.values() for name in names}
    assert allowed <= set(core.STEP_TOOLS)


@pytest.mark.parametrize("error", ["NOT_FOUND", "UNAVAILABLE", "LIMIT_EXCEEDED"])
def test_tool_that_returned_an_error_says_it_stopped(error):
    run = _run(tool_calls=[_call("t1", "structure_reasons", {"error": error})])

    [tool_step] = [s for s in core.render_steps(run, _sug()) if s.stage == "조사"]

    assert tool_step.text == "사유를 조건으로 나누려다 멈췄어요"


def test_compromise_preview_adds_the_count_that_meets_both_sides():
    preview = {"passed_count": 9, "with_keys_count": 3, "with_labels": ["조용한 곳"], "funnel": {}}
    run = _run(tool_calls=[_call("p1", "preview_filter", preview, {"category": "카페", "with_keys": ["quiet"]})])

    [step] = [s for s in core.render_steps(run, _sug()) if s.stage == "미리 찾기"]

    assert step.text == "지금 조건으로 미리 찾아봤어요 · 9곳 남아요 · 두 의견을 다 맞추는 곳 3곳"


@pytest.mark.parametrize("result, by, by_detail, text", [
    ({"status": "found", "statements": 1, "reused": False}, "ai", "모델 → 코드", "웹에서 찾아봤어요 · 출처 1개"),
    ({"status": "not_found", "statements": 0, "reused": False}, "ai", "모델 → 코드",
     "웹에서 찾아봤지만 확인되는 내용이 없었어요"),
    ({"status": "failed", "statements": 0, "reused": False}, "ai", "모델 → 코드", "웹에서 찾아보다 멈췄어요"),
    ({"status": "paused", "statements": 0, "reused": False}, "code", None, "오늘은 웹 확인을 쉬어요"),
    ({"status": "found", "statements": 2, "reused": True}, "code", None,
     "하루 안에 웹에서 찾은 결과를 다시 썼어요 · 출처 2개"),
    ({"status": "not_found", "statements": 0, "reused": True}, "code", None,
     "하루 안에 웹에서 찾아본 결과를 다시 썼어요 · 확인되는 내용이 없었어요"),
])
def test_web_check_line_per_status(result, by, by_detail, text):
    run = _run(tool_calls=[_call("w1", "web_check", result)])

    [step] = [s for s in core.render_steps(run, _sug()) if s.stage == "웹 확인"]

    assert (step.role, step.by, step.by_detail, step.text) == ("검증", by, by_detail, text)


def test_verification_counts_removed_claims_lines_and_buttons():
    verification = {"claims": {"kept": ["c1", "c2"], "removed": [{"id": "c3", "reason": "count_mismatch"}]},
                    "lines": {"kept": 1, "removed": [{"index": 1}, {"index": 2}]},
                    "actions": {"kept": 0, "removed": [{"index": 0}]}}

    [step] = [s for s in core.render_steps(_run(verification=verification), _sug()) if s.stage == "검증"]

    assert step.text == "숫자와 인용 3개를 지도와 대조했어요 · 맞지 않은 1개는 뺐어요 · 문장 2개는 뺐어요 · 버튼 1개는 뺐어요"


def test_silent_or_signal_mismatch_verification_has_no_verify_line():
    for verification in ({"decision": "silent"}, {"decision": "suggest", "signal": False, "failed_step": 2}):
        assert "검증" not in [s.stage for s in core.render_steps(_run(verification=verification), _sug())]


def test_no_run_means_no_steps():
    assert core.render_steps(None, _sug()) == []


def test_after_withdrawal_tool_and_verify_lines_are_gone():
    """탈퇴(13절)로 tool_calls가 []로, verification이 NULL로 비면 조사·미리 찾기·웹 확인·검증 줄이 빠진다(17절 16번에 더함)."""
    run = _run(tool_calls=[], verification=None)

    steps = core.render_steps(run, _sug(facts=FACTS))

    assert [s.stage for s in steps] == ["감지", "우리 데이터", "재확인"]


def test_reason_text_pin_names_aliases_and_urls_in_the_record_never_reach_the_steps():
    """기록에 사람 글, 핀 이름, 별칭, URL이 섞여 들어가 있어도(옛 기록, 리댁션 밖 칸) 작업 기록은 숫자와 고정 문구뿐이다."""
    leaky = [
        _call("p1", "preview_filter", {"passed_count": 2, "with_labels": [REASON_TEXT], "funnel": {}}),
        _call("t1", "get_reaction_matrix", {"members": ["m1", "m2"], "pins": [{"pin_id": "p1", "name": PIN_NAME}],
                                            "total": 1}, {"category": PIN_NAME}),
        _call("t2", "get_reasons", {"reasons": [{"reaction_id": "r1", "text": REASON_TEXT, "member_alias": "m1"}]},
              {"types": [REASON_TEXT]}),
        _call("w1", "web_check", {"status": "found", "statements": 1, "reused": False, "url": URL, "text": REASON_TEXT}),
    ]
    run = _run(tool_calls=leaky, verification={"claims": {"kept": [{"text": REASON_TEXT}], "removed": []}})

    dumped = json.dumps([s.model_dump() for s in core.render_steps(run, _sug(facts=[{"pin_id": "p1", "fact_key": "x",
                                                                                       "web": {"source_url": URL}}]))],
                        ensure_ascii=False)

    for leaked in (REASON_TEXT, PIN_NAME, URL, "m1", "m2", "p1", "r1"):
        assert leaked not in dumped


def test_rendered_suggestion_carries_the_steps_of_its_run():
    sig = core.make_signal("category_gap", category="카페", evidence=[("p1", "confirmed", NOW), ("p2", "confirmed", NOW)],
                           features={"affected_members": 3})
    draft = core.render_template(sig)
    row = SimpleNamespace(id="s1", diagnosis="category_gap", category="카페", title=draft.title, claims=draft.claims,
                          analysis=None, advice=draft.advice, actions=draft.actions, facts=[], fingerprint=sig.fingerprint,
                          created_at=NOW, expires_at=NOW)
    run = _run(signals=[core.signal_record(replace(sig, id="s1"))])

    out = core.render_suggestion(row, core.RenderRefs({}), run)

    assert [s.stage for s in out.steps] == ["감지", "재확인"]
    assert core.render_suggestion(row, core.RenderRefs({})).steps == []   # run 행이 지워졌다(30일 정리)


# ---------------------------------------------------------------- 살펴본 상태 (21.3)

def _obs(outcome, blocked=()):
    return SimpleNamespace(outcome=outcome, blocked=list(blocked))


@pytest.mark.parametrize("outcome, blocked, notice", [
    ("model_failed", (), core.OBSERVATION_NOTICES["failed"]),
    ("invalid_schema", (), core.OBSERVATION_NOTICES["failed"]),
    ("error", (), core.OBSERVATION_NOTICES["failed"]),
    ("invalid_claims", (), core.OBSERVATION_NOTICES["invalid_claims"]),
    ("blocked", ({"signal_id": "s1", "reason": "duplicate"}, {"signal_id": "s2", "reason": "model_cap"}),
     core.OBSERVATION_NOTICES["model_cap"]),
    ("trip_ended", (), core.OBSERVATION_NOTICES["trip_ended"]),
    ("blocked", ({"signal_id": "s1", "reason": "backoff"},), None),
    ("no_signal", (), None),
    ("silent", (), None),
    ("unknown", (), None),
    ("stale", (), None),
    ("suggested", (), None),
    ("map_deleted", (), None),
])
def test_notice_per_outcome(outcome, blocked, notice):
    assert core.observation_notice(_obs(outcome, blocked)) == notice


def test_notices_are_short_fixed_phrases_without_numbers():
    for notice in core.OBSERVATION_NOTICES.values():
        assert len(notice) <= 100 and not any(ch.isdigit() for ch in notice)


def test_no_observation_yet_means_no_time_and_no_notice():
    state = core.agent_state(AgentSettings(enabled=True), None, viewed=False)

    assert state.observation.model_dump() == {"checked_at": None, "notice": None}


def test_notice_only_when_mode_is_on_and_nothing_is_shown():
    failed = _obs("model_failed")
    on, off = AgentSettings(enabled=True), AgentSettings(enabled=False)
    sig = core.make_signal("category_gap", category="카페", evidence=[("p1", "confirmed", NOW)], features={})
    draft = core.render_template(sig)
    row = SimpleNamespace(id="s1", diagnosis="category_gap", category="카페", title=draft.title, claims=draft.claims,
                          analysis=None, advice=draft.advice, actions=draft.actions, facts=[], created_at=NOW,
                          expires_at=NOW)
    active = core.render_suggestion(row, core.RenderRefs({}))

    quiet = core.agent_state(on, None, viewed=False, checked_at=NOW, latest_observation=failed)
    with_suggestion = core.agent_state(on, active, viewed=False, checked_at=NOW, latest_observation=failed)
    mode_off = core.agent_state(off, None, viewed=False, checked_at=NOW, latest_observation=failed)

    assert quiet.observation.model_dump() == {"checked_at": NOW, "notice": core.OBSERVATION_NOTICES["failed"]}
    assert with_suggestion.observation.model_dump() == {"checked_at": NOW, "notice": None}
    assert mode_off.observation.model_dump() == {"checked_at": NOW, "notice": None}

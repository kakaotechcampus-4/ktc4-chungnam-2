"""추천 막힘 조언의 순수 판단(명세 9절, 11.2, #587) — 대상 판정, 근거 줄의 표시와 종류, 검증, 렌더. DB 없이 돈다.

17절 2(soft_relax에서 본인 줄만 open_evidence, 남의 줄은 문장만), 반경 상한(WIDEN_LIMIT)을 넘는 배율, 종류별 버튼, 근거 글과
구성원 이름이 문장과 저장에 들어가지 않는 것.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent import core
from agent.schemas import Action, AdviceLine, CountClaim, QuoteClaim, RunAdviceOutput, ToolClaim

RUN = "run-1"
OWN, OTHER, VAGUE = "line-own", "line-other", "line-vague"
OWN_TEXT, OTHER_TEXT = "좁아서 다리를 펼 수가 없었어요", "사람이 너무 많아서 정신없었어요"
NAMES = ["김철수", "이영희"]
FUNNEL = core.funnel_view({"result_count": 1, "passed_count": 1, "funnel": [
    {"label": "카테고리 후보 풀", "removed_count": 0}, {"label": "반경 밖 제거", "removed_count": 4},
    {"label": "실격 조건 제거", "removed_count": 9}, {"label": "이미 제안·거절됨", "removed_count": 2},
    {"label": "상위 3곳 선정", "removed_count": 0},
]})
LINES = core.advice_evidence([
    {"line_id": OWN, "author_id": "u1", "text": OWN_TEXT, "badge": "required", "fact_key": "spacious", "wants": True,
     "is_active": True, "chip_id": None},
    {"line_id": OTHER, "author_id": "u2", "text": OTHER_TEXT, "badge": "required", "fact_key": "is_crowded_large",
     "wants": None, "is_active": True, "chip_id": None},
    {"line_id": VAGUE, "author_id": "u1", "text": "그냥 그래요", "badge": "required", "fact_key": None, "wants": None,
     "is_active": True, "chip_id": None},
], "u1", {"spacious": "넓은 곳", "is_crowded_large": "붐비는 대형 장소"})


def _sim(factor=None, lines=(), gained=3, within=True):
    side = {"result_count": 1, "funnel": [], "passed": 1}
    return {"radius_factor": factor, "disable_line_ids": list(lines), "within_widen_limit": within,
            "before": side, "after": {**side, "passed": 1 + gained}, "gained": gained}


NEXT = 20 / 15   # 도보 15분에서 버튼 한 번(5분) 넓힌 배율(#677)
RESULTS = {
    "t0": FUNNEL,
    "t1": {"lines": LINES, "total": 3},
    "t2": _sim(lines=[OWN], gained=5),
    "t3": _sim(lines=[OTHER], gained=4),
    "t4": _sim(factor=2.0, gained=6),                   # 상한(30분)까지
    "t5": _sim(factor=3.0, gained=9, within=False),
    "t6": _sim(factor=NEXT, gained=2),                  # 버튼 한 번
}
NAMES_OF = {"t0": "get_run_funnel", "t1": "get_run_evidence", "t2": "simulate_filter", "t3": "simulate_filter",
            "t4": "simulate_filter", "t5": "simulate_filter", "t6": "simulate_filter"}


def _ctx(**over):
    fields = dict(
        run_id=RUN, tool_results=RESULTS, tool_names=NAMES_OF, own_lines={OWN: True, OTHER: False, VAGUE: True},
        evidence_texts=[OWN_TEXT, OTHER_TEXT, "그냥 그래요"], radius=core.radius_limits(15, 30, 5), member_names=NAMES,
    )
    return core.AdviceContext(**(fields | over))


def tc(cid, call_id, path, value):
    return ToolClaim(id=cid, kind="tool_result", call_id=call_id, path=path, value=value)


def line(text, *basis, guess=False):
    return AdviceLine(text=text, basis=list(basis), is_guess=guess)


def act(type_, *basis):
    return Action(type=type_, basis=list(basis))


def out(kind, claims, advice, actions=(), decision="suggest"):
    return RunAdviceOutput(decision=decision, kind=kind, claims=claims, advice=advice, actions=list(actions))


# ---------------------------------------------------------------- 대상 판정 (9절)

@pytest.mark.parametrize("status, results, runs, target", [
    ("done", 2, 1, True),        # 결과 3곳 미만
    ("done", 0, 1, True),
    ("done", 3, 2, False),       # 결과 3곳, 같은 카테고리 run 2개
    ("done", 3, 3, True),        # 같은 카테고리 run 3개 이상
    ("executing", 0, 5, False),  # 완료 전
    ("collecting_evidence", 0, 1, False),
])
def test_target(status, results, runs, target):
    assert core.run_advice_target(status, results, runs) is target


def test_same_category_runs_counts_up_to_this_run_only():
    at = datetime(2026, 10, 17, tzinfo=timezone.utc)
    recent = [{"created_at": at + timedelta(hours=h)} for h in (2, 1, 0, -1, -2)]   # 최근순, 이 run은 0
    assert core.same_category_runs(recent, at) == 3   # 나중 run 둘은 세지 않는다


@pytest.mark.parametrize("walk, factor, next_factor", [
    (15, 2.0, 20 / 15), (20, 1.5, 25 / 20), (25, 1.2, 30 / 25),
    (28, 1.07, 30 / 28),   # 한 단계가 상한을 넘으면 상한까지
    (30, 1.0, None), (35, 0.85, None),   # 이미 상한 — 버튼이 넓힐 수 없다
])
def test_radius_limits(walk, factor, next_factor):
    assert core.radius_limits(walk, 30, 5) == {"walk_min": walk, "max_walk_min": 30, "max_radius_factor": factor,
                                               "next_radius_factor": next_factor}


def test_next_radius_factor_is_not_rounded():
    """시뮬레이션 반경이 버튼 한 번 뒤의 반경과 같아야 한다(#677) — 1200m × 20/15는 반올림하면 1600m, 1.33이면 1596m다."""
    factor = core.radius_limits(15, 30, 5)["next_radius_factor"]
    assert factor == 20 / 15 and round(1200 * factor) == 20 * 80


@pytest.mark.parametrize("top_label", ["상위 3곳 선정", "추천 3곳 고르기"])
def test_passed_and_gained_come_from_passed_count_not_the_stage_label(top_label):
    """passed는 recommend가 센 passed_count 그대로다 — 깔때기 라벨 문구가 바뀌어도 passed와 gained가 같다(#587)."""
    def outcome(removed_at_top, passed_count):
        funnel = [{"label": "실격 조건 제거", "removed_count": 4}, {"label": top_label, "removed_count": removed_at_top}]
        return {"result_count": 3, "funnel": funnel, "passed_count": passed_count}

    view = core.funnel_view(outcome(5, 8))
    sim = core.simulate_view({"before": outcome(5, 8), "after": outcome(7, 10)}, radius_factor=None,
                             disable_line_ids=[OWN], walk_min=15, limit_walk_min=30)

    assert (view["result_count"], view["passed"], view["funnel"][-1]["label"]) == (3, 8, top_label)
    assert (sim["before"]["passed"], sim["after"]["passed"], sim["gained"]) == (8, 10, 2)


# ---------------------------------------------------------------- 근거 줄 (10절 get_run_evidence)

@pytest.mark.parametrize("fields, kind", [
    ({"fact_key": "spacious", "wants": True}, "condition"),
    ({"fact_key": "is_crowded_large", "wants": None}, "condition"),   # hard 키는 방향 없이 거른다
    ({"fact_key": None, "chip_id": "food_expensive", "text": "비싸요"}, "not_filtered"),   # 가격 (#423)
    ({"fact_key": None, "text": "저 새우 알레르기 있어요"}, "not_filtered"),   # 안전 조건 (#425)
    ({"fact_key": None, "chip_id": "common_far", "text": "너무 멀어요"}, "vague"),
    ({"fact_key": None, "text": "그냥 별로"}, "vague"),
])
def test_evidence_kind(fields, kind):
    assert core.evidence_kind({"wants": None, "chip_id": None, "text": "", **fields}) == kind


def test_evidence_lines_show_only_self_or_other_member():
    rows = core.advice_evidence([
        {"line_id": "a", "author_id": "u1", "text": "넓은 데 가요", "badge": "required", "fact_key": "spacious",
         "wants": True, "is_active": True, "chip_id": None},
        {"line_id": "b", "author_id": "u2", "text": "갑각류 알러지 있어요", "badge": "required", "fact_key": None,
         "wants": None, "is_active": True, "chip_id": None},
    ], "u1", {"spacious": "넓은 곳"})

    assert [r["author"] for r in rows] == ["본인", "다른 구성원"]
    assert rows[0]["label"] == "넓은 곳 원함"
    assert rows[1]["text"] is None and rows[1]["kind"] == "not_filtered"   # 알러지 원문은 모델에도 가지 않는다
    assert "u1" not in str(rows) and "u2" not in str(rows)


def test_advice_input_has_funnel_as_call_t0_and_no_people():
    meta = {"category": "카페", "result_count": 1, "default_radius_walk_min": 20, "widen_limit_walk_min": 30,
            "widen_step_walk_min": 5, "requested_by": "u1", "map_id": "m1", "run_id": RUN}
    data = core.advice_input(meta, 2, FUNNEL)

    assert data["funnel"] == {"call_id": "t0", "result": FUNNEL}
    assert (data["radius"]["max_radius_factor"], data["radius"]["next_radius_factor"]) == (1.5, 1.25)
    assert {"requested_by", "map_id", "run_id"}.isdisjoint(data)


# ---------------------------------------------------------------- 검증 — soft_relax (17절 2)

def test_soft_relax_button_only_for_own_line_and_other_line_stays_as_a_fact():
    advice = out("soft_relax",
                 [tc("c1", "t2", "gained", 5), tc("c2", "t1", "lines.0.label", "넓은 곳 원함"),
                  tc("c3", "t3", "gained", 4), tc("c4", "t1", "lines.1.label", "붐비는 대형 장소")],
                 [line("「{c2.value}」 조건을 끄면 {c1.value}곳이 더 남아요", "c1", "c2"),
                  line("다른 구성원의 「{c4.value}」 조건 때문에 {c3.value}곳이 빠졌어요", "c3", "c4")],
                 [act("open_evidence", "c1"), act("open_evidence", "c3")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.outcome == "advised"
    assert [a["params"]["evidence_line_ids"] for a in v.draft.actions] == [[OWN]]
    assert v.draft.actions[0] == {"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                                  "params": {"run_id": RUN, "evidence_line_ids": [OWN]}}
    assert v.record["actions"]["removed"] == [{"index": 1, "reason": "not_own_line"}]
    assert len(v.draft.advice) == 2   # 남의 줄 문장은 버튼 없이 남는다


def test_open_evidence_mixing_own_and_other_lines_is_removed():
    advice = out("soft_relax", [tc("c1", "t2", "gained", 5), tc("c2", "t3", "gained", 4)],
                 [line("조건 두 개를 끄면 {c1.value}곳과 {c2.value}곳이 더 남아요", "c1", "c2")],
                 [act("open_evidence", "c1", "c2")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.draft.actions == []
    assert v.record["actions"]["removed"] == [{"index": 0, "reason": "not_own_line"}]


def test_vague_reason_button_points_at_own_line_from_evidence_list():
    advice = out("vague_reason", [tc("c1", "t1", "lines.2.line_id", VAGUE)],
                 [line("조건을 읽지 못한 근거가 있어요", "c1"),
                  line("'조용한 곳이 좋아요'처럼 적으면 반영돼요", "c1", guess=True)],
                 [act("open_evidence", "c1")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.outcome == "advised"
    assert v.draft.actions[0]["label"] == "근거 확인하기"
    assert v.draft.actions[0]["params"]["evidence_line_ids"] == [VAGUE]


# ---------------------------------------------------------------- 검증 — 반경 (WIDEN_LIMIT)

def test_widen_radius_beyond_the_limit_is_removed():
    advice = out("radius", [tc("c1", "t5", "gained", 9)],
                 [line("반경을 넓히면 {c1.value}곳이 더 나와요", "c1")], [act("widen_radius", "c1")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.record["claims"]["removed"] == [{"id": "c1", "reason": "radius_over_limit"}]
    assert v.outcome == "invalid_claims" and v.draft == core.EMPTY_ADVICE


def test_widen_radius_within_the_limit_is_kept_and_over_limit_line_dropped():
    advice = out("radius", [tc("c1", "t6", "gained", 2), tc("c2", "t5", "gained", 9)],
                 [line("반경을 넓히면 {c1.value}곳이 더 나와요", "c1"), line("더 넓히면 {c2.value}곳이에요", "c2")],
                 [act("widen_radius", "c1"), act("widen_radius", "c2")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.draft.actions == [{"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": RUN}}]
    assert [a["slot_text"] for a in v.draft.advice] == ["반경을 넓히면 {c1.value}곳이 더 나와요"]


def test_widen_radius_button_only_for_the_one_press_simulation():
    """버튼은 한 번에 5분만 넓힌다(#677). 상한까지 넓힌 숫자에는 버튼을 붙이지 않는다(not_next_step) — 문장은 사실이라 남는다."""
    advice = out("radius", [tc("c1", "t4", "gained", 6), tc("c2", "t6", "gained", 2)],
                 [line("끝까지 넓히면 {c1.value}곳이 더 나와요", "c1"), line("한 번 넓히면 {c2.value}곳이에요", "c2")],
                 [act("widen_radius", "c1"), act("widen_radius", "c2")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.record["actions"]["removed"] == [{"index": 0, "reason": "not_next_step"}]
    assert v.draft.actions == [{"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": RUN}}]
    assert len(v.draft.advice) == 2


@pytest.mark.parametrize("factor, kept", [
    (1.3333333333, True),    # 부동소수 오차 안
    (1.33, False),           # 모델이 줄여 쓴 배율 — 1596m라 버튼 결과와 다르다
    (1.5, False),
])
def test_widen_radius_needs_the_exact_next_factor(factor, kept):
    results = RESULTS | {"t7": _sim(factor=factor, gained=2)}
    names = NAMES_OF | {"t7": "simulate_filter"}
    advice = out("radius", [tc("c1", "t7", "gained", 2)], [line("넓히면 {c1.value}곳이 더 나와요", "c1")],
                 [act("widen_radius", "c1")])

    v = core.verify_run_advice(advice, _ctx(tool_results=results, tool_names=names))

    assert (len(v.draft.actions) == 1) is kept
    assert v.record["actions"]["removed"] == ([] if kept else [{"index": 0, "reason": "not_next_step"}])


def test_widen_radius_when_already_at_the_limit_is_removed():
    advice = out("radius", [tc("c1", "t4", "gained", 6)],
                 [line("반경을 넓히면 {c1.value}곳이 더 나와요", "c1")], [act("widen_radius", "c1")])

    v = core.verify_run_advice(advice, _ctx(radius=core.radius_limits(30, 30, 5)))

    assert v.record["actions"]["removed"] == [{"index": 0, "reason": "radius_limit"}]
    assert v.draft.actions == []


# ---------------------------------------------------------------- 검증 — claim, 문장, 버튼, 성립

def test_only_tool_claims_and_never_evidence_text():
    advice = out("soft_relax", [
        tc("c1", "t2", "gained", 5),
        tc("c2", "t1", "lines.0.text", OWN_TEXT),                                     # 근거 글 경로
        QuoteClaim(id="c3", kind="quote", reaction_id="r1", text=OWN_TEXT),            # 인용은 조언에 없다
        CountClaim(id="c4", kind="count", subject="map", subject_id=None, metric="pins", value=3),
        tc("c5", "t2", "gained", 99),                                                   # 도구 결과와 다른 값
        tc("c6", "t9", "gained", 1),                                                    # 없는 호출
    ], [line("조건을 끄면 {c1.value}곳이 더 남아요", "c1"), line("「{c2.value}」 때문이에요", "c2")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.record["claims"] == {"kept": ["c1"], "removed": [
        {"id": "c2", "reason": "text_path"}, {"id": "c3", "reason": "kind"}, {"id": "c4", "reason": "kind"},
        {"id": "c5", "reason": "tool_mismatch"}, {"id": "c6", "reason": "tool_call_not_found"},
    ]}
    assert [a["slot_text"] for a in v.draft.advice] == ["조건을 끄면 {c1.value}곳이 더 남아요"]


@pytest.mark.parametrize("text, reason", [
    ("조건을 끄면 5곳이 더 남아요", "digit"),
    ("김철수 님의 조건 때문에 {c1.value}곳이 빠졌어요", "member_name"),
    ("「좁아서 다리를 펼 수가」 때문에 {c1.value}곳이 빠졌어요", "copied"),    # 근거 글을 슬롯 밖에서 옮겨 씀
    ("이 조건을 빼고 확정하세요 {c1.value}", "forbidden"),
    ("{c9.value}곳이 더 남아요", "basis"),
])
def test_sentences_are_checked_like_diagnosis(text, reason):
    basis = ["c9"] if reason == "basis" else ["c1"]
    advice = out("soft_relax", [tc("c1", "t2", "gained", 5)], [line(text, *basis)], [act("open_evidence", "c1")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.record["lines"]["removed"] == [{"index": 0, "reason": reason}]


@pytest.mark.parametrize("kind, action_type", [
    ("radius", "open_evidence"), ("exhausted", "widen_radius"), ("exhausted", "open_evidence"),
    ("soft_relax", "widen_radius"), ("vague_reason", "show_pins"),
])
def test_buttons_follow_the_kind(kind, action_type):
    claims = [tc("c1", "t0", "funnel.3.removed_count", 2), tc("c2", "t4", "gained", 6), tc("c3", "t2", "gained", 5)]
    advice = out(kind, claims, [line("이미 보여 드린 곳이 {c1.value}곳이에요", "c1")],
                 [act(action_type, "c1", "c2", "c3")])

    v = core.verify_run_advice(advice, _ctx())

    assert v.record["actions"]["removed"] == [{"index": 0, "reason": "type"}]


def test_exhausted_needs_the_funnel_claim():
    ok = out("exhausted", [tc("c1", "t0", "funnel.3.removed_count", 2)],
             [line("이미 보여 드렸거나 거절한 곳이 {c1.value}곳 빠졌어요", "c1")])
    no_funnel = out("exhausted", [tc("c1", "t2", "gained", 5)], [line("{c1.value}곳이 더 남아요", "c1")])

    assert core.verify_run_advice(ok, _ctx()).outcome == "advised"
    failed = core.verify_run_advice(no_funnel, _ctx())
    assert (failed.outcome, failed.record["failed_step"]) == ("invalid_claims", 7)


@pytest.mark.parametrize("decision", ["silent", "unknown"])
def test_silence_is_kept_as_an_empty_advice(decision):
    v = core.verify_run_advice(out("exhausted", [], [], decision=decision), _ctx())
    assert (v.outcome, v.draft) == (decision, core.EMPTY_ADVICE)


def test_stored_draft_has_no_text_or_names():
    advice = out("soft_relax",
                 [tc("c1", "t2", "gained", 5), tc("c2", "t1", "lines.0.label", "넓은 곳 원함"), tc("c3", "t3", "gained", 4)],
                 [line("「{c2.value}」 조건을 끄면 {c1.value}곳이 더 남아요", "c1", "c2"),
                  line("다른 구성원의 조건 때문에 {c3.value}곳이 빠졌어요", "c3")],
                 [act("open_evidence", "c1")])

    stored = str(core.verify_run_advice(advice, _ctx()).draft)

    for secret in (OWN_TEXT, OTHER_TEXT, *NAMES, "u1", "u2"):
        assert secret not in stored


# ---------------------------------------------------------------- 렌더

def _row(kind, claims, advice, actions=()):
    return SimpleNamespace(kind=kind, claims=claims, advice=advice, actions=list(actions))


def test_render_fills_tool_values():
    row = _row("soft_relax", [tc("c1", "t2", "gained", 5).model_dump(), tc("c2", "t1", "lines.0.label", "넓은 곳 원함").model_dump()],
               [{"slot_text": "「{c2.value}」 조건을 끄면 {c1.value}곳이 더 남아요", "is_guess": False}],
               [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                 "params": {"run_id": RUN, "evidence_line_ids": [OWN]}}])

    rendered = core.render_run_advice(RUN, row)

    assert rendered.model_dump(mode="json") == {
        "run_id": RUN, "kind": "soft_relax",
        # 조언은 tool_result claim만이라 text 조각 하나다(#717)
        "advice": [{"segments": [{"kind": "text", "text": "「넓은 곳 원함」 조건을 끄면 5곳이 더 남아요"}], "is_guess": False}],
        "actions": [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                     "params": {"run_id": RUN, "evidence_line_ids": [OWN]}}],
    }


def test_render_empty_advice_is_none():
    assert core.render_run_advice(RUN, _row(None, [], [])) is None
    assert core.render_run_advice(RUN, None) is None
    # 렌더 결과에 금지 표현이 생기면 그 문장을 빼고, 남는 것이 없으면 None
    row = _row("exhausted", [tc("c1", "t1", "lines.0.label", "확정하세요").model_dump()],
               [{"slot_text": "「{c1.value}」", "is_guess": False}])
    assert core.render_run_advice(RUN, row) is None

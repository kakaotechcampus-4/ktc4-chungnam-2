"""추천 막힘 조언의 순수 판단(명세 9절, #587, #750) — 대상 판정, 근거 줄의 표시와 종류, 필요한 시뮬레이션, 종류·문장·버튼
고르기, 렌더. DB 없이 돈다. 평가셋 25건은 test_advice_cases.py가 본다.

17절 2(soft_relax에서 본인 줄만 open_evidence, 남의 줄은 문장만), 반경은 버튼 한 번의 배율만, 뚜렷한 탈락(ADVICE_CLEAR_DROP),
근거 글과 구성원이 문장과 저장에 들어가지 않는 것.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent import core
from agent.constants import ADVICE_CLEAR_DROP, ADVICE_MAX_RELAX_LINES

RUN = "run-1"
OWN, OTHER, VAGUE = "line-own", "line-other", "line-vague"
OWN_TEXT, OTHER_TEXT = "좁아서 다리를 펼 수가 없었어요", "사람이 너무 많아서 정신없었어요"
LABELS = {"spacious": "넓은 곳", "is_crowded_large": "붐비는 대형 장소", "quiet": "조용한 곳"}
NEXT = 20 / 15   # 도보 15분에서 버튼 한 번(5분) 넓힌 배율(#677)


def raw_line(line_id, author, *, fact_key=None, wants=None, text="", active=True, chip_id=None, reason=None):
    """recommend.api.get_run_evidence의 한 줄."""
    return {"line_id": line_id, "author_id": author, "text": text, "badge": "required", "fact_key": fact_key,
            "wants": wants, "is_active": active, "chip_id": chip_id, "enforced": fact_key is not None and reason is None,
            "not_enforced_reason": reason if reason else (None if fact_key else "no_key")}


RAW_LINES = [
    raw_line(OWN, "u1", fact_key="spacious", wants=True, text=OWN_TEXT),
    raw_line(OTHER, "u2", fact_key="is_crowded_large", text=OTHER_TEXT),
    raw_line(VAGUE, "u1", text="그냥 그래요"),
]
LINES = core.advice_evidence(RAW_LINES, "u1", LABELS)


def funnel(radius=0, disqualify=0, excluded=0, closed=0):
    return core.funnel_view({"result_count": 1, "passed_count": 1, "funnel": [
        {"label": "카테고리 후보 풀", "removed_count": 0}, {"label": core.RADIUS_STAGE, "removed_count": radius},
        {"label": "영업 종료 제거", "removed_count": closed}, {"label": core.DISQUALIFY_STAGE, "removed_count": disqualify},
        {"label": core.EXCLUDED_STAGE, "removed_count": excluded}, {"label": "상위 3곳 선정", "removed_count": 0},
    ]})


def sim(gained, factor=None, lines=()):
    return {"radius_factor": factor, "disable_line_ids": list(lines), "gained": gained}


def choose(f, sims, lines=LINES, next_factor=NEXT):
    return core.choose_run_advice(RUN, f, lines, sims, next_factor)


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


@pytest.mark.parametrize("walk, next_factor", [
    (15, 20 / 15), (20, 25 / 20), (25, 30 / 25),
    (28, 30 / 28),   # 한 단계가 상한을 넘으면 상한까지
    (30, None), (35, None),   # 이미 상한 — 버튼이 넓힐 수 없다
])
def test_next_radius_factor(walk, next_factor):
    meta = {"default_radius_walk_min": walk, "widen_limit_walk_min": 30, "widen_step_walk_min": 5}
    assert core.next_radius_factor(meta) == next_factor


def test_next_radius_factor_is_not_rounded():
    """시뮬레이션 반경이 버튼 한 번 뒤의 반경과 같아야 한다(#677) — 1200m × 20/15는 반올림하면 1600m, 1.33이면 1596m다."""
    factor = core.next_radius_factor({"default_radius_walk_min": 15, "widen_limit_walk_min": 30, "widen_step_walk_min": 5})
    assert factor == 20 / 15 and round(1200 * factor) == 20 * 80


@pytest.mark.parametrize("top_label", ["상위 3곳 선정", "추천 3곳 고르기"])
def test_passed_and_gained_come_from_passed_count_not_the_stage_label(top_label):
    """passed는 recommend가 센 passed_count 그대로다 — 깔때기 라벨 문구가 바뀌어도 passed와 gained가 같다(#587)."""
    def outcome(removed_at_top, passed_count):
        entries = [{"label": core.DISQUALIFY_STAGE, "removed_count": 4}, {"label": top_label, "removed_count": removed_at_top}]
        return {"result_count": 3, "funnel": entries, "passed_count": passed_count}

    view = core.funnel_view(outcome(5, 8))
    result = core.simulate_view({"before": outcome(5, 8), "after": outcome(7, 10)}, radius_factor=None,
                                disable_line_ids=[OWN])

    assert (view["result_count"], view["passed"], view["funnel"][-1]["label"]) == (3, 8, top_label)
    assert (result["before"]["passed"], result["after"]["passed"], result["gained"]) == (8, 10, 2)


# ---------------------------------------------------------------- 근거 줄

@pytest.mark.parametrize("fields, kind", [
    ({"fact_key": "spacious", "wants": True, "enforced": True}, "condition"),
    ({"fact_key": "is_crowded_large", "wants": None, "enforced": True}, "condition"),   # hard 키는 방향 없이 거른다
    ({"fact_key": None, "not_enforced_reason": "no_key", "chip_id": "food_expensive", "text": "비싸요"}, "not_filtered"),   # 가격 (#423)
    ({"fact_key": None, "not_enforced_reason": "no_key", "text": "저 새우 알레르기 있어요"}, "not_filtered"),   # 안전 조건 (#425)
    ({"fact_key": None, "not_enforced_reason": "no_key", "chip_id": "common_far", "text": "너무 멀어요"}, "vague"),
    ({"fact_key": None, "not_enforced_reason": "no_key", "text": "그냥 별로"}, "vague"),
    ({"fact_key": "quiet", "not_enforced_reason": "no_direction"}, "vague"),   # 다시 적으면 반영된다
    ({"fact_key": "season_snow", "not_enforced_reason": "off_season"}, "not_filtered"),
    ({"fact_key": "is_crowded_large", "not_enforced_reason": "not_for_category"}, "not_filtered"),
])
def test_evidence_kind(fields, kind):
    base = {"wants": None, "chip_id": None, "text": "", "enforced": False}
    assert core.evidence_kind(base | fields) == kind


def test_evidence_lines_carry_only_own_flag_label_and_kind():
    rows = core.advice_evidence([
        raw_line("a", "u1", fact_key="spacious", wants=True, text="넓은 데 가요"),
        raw_line("b", "u2", text="갑각류 알러지 있어요"),
    ], "u1", LABELS)

    assert rows == [
        {"line_id": "a", "own": True, "kind": "condition", "label": "넓은 곳 원함", "is_active": True},
        {"line_id": "b", "own": False, "kind": "not_filtered", "label": None, "is_active": True},
    ]   # 글, 쓴 사람 id는 절차에 들어가지 않는다


# ---------------------------------------------------------------- 필요한 시뮬레이션

def test_simulations_follow_the_clear_stages_without_waiting_on_each_other():
    """뚜렷한 단계마다 볼 것을 모두 고른다 — 반경은 버튼 한 번의 배율 하나, 실격 조건은 켜진 조건 줄마다."""
    wanted = core.advice_simulations(funnel(radius=9, disqualify=6), LINES, NEXT)

    assert wanted == {
        "t2": {"radius_factor": NEXT, "disable_line_ids": []},
        "t3": {"radius_factor": None, "disable_line_ids": [OWN]},
        "t4": {"radius_factor": None, "disable_line_ids": [OTHER]},
    }


@pytest.mark.parametrize("f, next_factor, expected", [
    (funnel(radius=4, disqualify=4, excluded=4), NEXT, {}),             # 뚜렷한 단계 없음
    (funnel(radius=9, excluded=12), NEXT, {}),                          # 「이미 제안·거절됨」이 먼저라 볼 것이 없다
    (funnel(radius=12, excluded=9, disqualify=6), NEXT, {"t2": {"radius_factor": NEXT, "disable_line_ids": []}}),
    (funnel(radius=12), None, {}),                                      # 이미 상한
])
def test_simulations_only_what_is_needed(f, next_factor, expected):
    assert core.advice_simulations(f, LINES, next_factor) == expected


def test_relaxable_lines_are_active_named_conditions_up_to_the_cap():
    lines = core.advice_evidence([
        raw_line("off", "u1", fact_key="quiet", wants=True, active=False),   # 이미 끈 줄
        raw_line("nameless", "u1", fact_key="no_such_key", wants=True),      # 이름이 없어 말할 수 없다
        raw_line("vague", "u1"),
        *[raw_line(f"c{i}", "u2", fact_key="spacious", wants=True) for i in range(ADVICE_MAX_RELAX_LINES + 1)],
    ], "u1", LABELS)

    wanted = core.advice_simulations(funnel(disqualify=9), lines, NEXT)

    assert [w["disable_line_ids"] for w in wanted.values()] == [[f"c{i}"] for i in range(ADVICE_MAX_RELAX_LINES)]


# ---------------------------------------------------------------- 종류 고르기

def test_soft_relax_button_only_for_own_line_and_other_line_stays_as_a_fact():
    draft = choose(funnel(disqualify=12), {"t2": sim(5, lines=[OWN]), "t3": sim(7, lines=[OTHER])})

    assert draft.kind == "soft_relax"
    assert [a["slot_text"] for a in draft.advice] == [
        "「{c1.value}」 조건을 빼면 {c2.value}곳이 더 남아요.", "「{c3.value}」 조건을 빼면 {c4.value}곳이 더 남아요.",
    ]
    assert [(c["call_id"], c["path"], c["value"]) for c in draft.claims] == [
        ("t1", "lines.1.label", "붐비는 대형 장소"), ("t3", "gained", 7), ("t1", "lines.0.label", "넓은 곳 원함"), ("t2", "gained", 5),
    ]
    assert draft.actions == [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                              "params": {"run_id": RUN, "evidence_line_ids": [OWN]}}]


def test_own_line_is_mentioned_even_when_it_gains_little():
    """남의 줄이 더 많이 걸렀어도 본인 줄에 gained가 있으면 그 줄을 말하고 버튼을 붙인다(9절)."""
    draft = choose(funnel(disqualify=12), {"t2": sim(1, lines=[OWN]), "t3": sim(9, lines=[OTHER])})

    assert [c["value"] for c in draft.claims if c["path"] == "gained"] == [9, 1]
    assert draft.actions[0]["params"]["evidence_line_ids"] == [OWN]


@pytest.mark.parametrize("second, mentioned", [(ADVICE_CLEAR_DROP - 1, 1), (ADVICE_CLEAR_DROP, 2)])
def test_second_line_only_when_it_clearly_gains(second, mentioned):
    two_own = core.advice_evidence([raw_line(OWN, "u1", fact_key="spacious", wants=True),
                                    raw_line("own2", "u1", fact_key="quiet", wants=True)], "u1", LABELS)

    draft = choose(funnel(disqualify=12), {"t2": sim(8, lines=[OWN]), "t3": sim(second, lines=["own2"])}, lines=two_own)

    assert len(draft.advice) == mentioned
    # 본인 줄이 둘이면 버튼 하나에 둘 다
    assert draft.actions[0]["params"]["evidence_line_ids"] == [OWN, "own2"][:mentioned]


def test_other_members_line_alone_has_no_button():
    draft = choose(funnel(disqualify=12), {"t2": sim(0, lines=[OWN]), "t3": sim(6, lines=[OTHER])})

    assert (draft.kind, len(draft.advice), draft.actions) == ("soft_relax", 1, [])


def test_radius_uses_only_the_one_press_simulation():
    """다른 배율(상한까지 등)의 숫자는 버튼을 눌렀을 때와 달라 쓰지 않는다(#677)."""
    to_limit = choose(funnel(radius=9), {"t2": sim(6, factor=2.0)})
    rounded = choose(funnel(radius=9), {"t2": sim(6, factor=1.33)})
    exact = choose(funnel(radius=9), {"t2": sim(2, factor=1.3333333333)})   # 부동소수 오차 안

    assert to_limit == rounded == core.choose_run_advice(RUN, funnel(radius=9), LINES, {}, NEXT)
    assert exact.kind == "radius" and exact.claims == [
        {"id": "c1", "kind": "tool_result", "call_id": "t2", "path": "gained", "value": 2}]
    assert exact.actions == [{"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": RUN}}]


def test_radius_that_gains_nothing_moves_to_the_next_stage():
    draft = choose(funnel(radius=12, disqualify=6), {"t2": sim(0, factor=NEXT), "t3": sim(4, lines=[OWN])})

    assert draft.kind == "soft_relax"


def test_radius_at_the_limit_moves_to_the_next_stage():
    draft = choose(funnel(radius=12, excluded=6), {}, next_factor=None)

    assert draft.kind == "exhausted"


def test_exhausted_points_at_the_funnel_and_has_no_button():
    draft = choose(funnel(radius=3, excluded=18), {})

    assert draft.claims == [{"id": "c1", "kind": "tool_result", "call_id": "t0", "path": "funnel.4.removed_count",
                             "value": 18}]
    assert [a["slot_text"] for a in draft.advice] == ["이미 보여 줬거나 거절한 {c1.value}곳은 다시 추천하지 않아요."]
    assert draft.actions == []


@pytest.mark.parametrize("drop", [ADVICE_CLEAR_DROP - 1, ADVICE_CLEAR_DROP])
def test_stages_below_the_clear_drop_are_not_used(drop):
    draft = choose(funnel(excluded=drop), {}, lines=[])

    assert draft.kind == ("exhausted" if drop >= ADVICE_CLEAR_DROP else None)


def test_equal_drops_follow_the_stage_order():
    """같은 수면 반경 → 실격 조건 → 이미 제안·거절됨 순서로 본다."""
    draft = choose(funnel(radius=7, excluded=7), {"t2": sim(1, factor=NEXT)})

    assert draft.kind == "radius"


def test_closed_hours_are_not_a_kind():
    """「영업 종료 제거」는 사람이 바꿀 수 없어 종류를 고르지 않는다 — vague 줄이 없으면 침묵."""
    no_vague = [line for line in LINES if line["kind"] != "vague"]

    assert choose(funnel(closed=20), {}, lines=no_vague) == core.EMPTY_ADVICE


@pytest.mark.parametrize("author, button", [("u1", True), ("u2", False)])
def test_vague_reason_button_only_for_own_line(author, button):
    lines = core.advice_evidence([raw_line("alg", "u1", text="땅콩 알러지가 있어요"),   # not_filtered — 세지 않는다
                                  raw_line(VAGUE, author, text="그냥 그래요")], "u1", LABELS)

    draft = choose(funnel(radius=2), {}, lines=lines)

    assert draft.kind == "vague_reason" and draft.decision == "advise"
    assert draft.claims == [{"id": "c1", "kind": "tool_result", "call_id": "t1", "path": "lines.1.line_id", "value": VAGUE}]
    assert [(a["slot_text"], a["is_guess"]) for a in draft.advice] == list(core.VAGUE_REASON_LINES)
    assert draft.actions == ([{"index": 0, "type": "open_evidence", "label": "근거 확인하기",
                               "params": {"run_id": RUN, "evidence_line_ids": [VAGUE]}}] if button else [])


def test_not_filtered_lines_alone_are_silent():
    lines = core.advice_evidence([raw_line("alg", "u1", text="땅콩 알러지가 있어요"),
                                  raw_line("price", "u2", text="비싸요", chip_id="food_expensive")], "u1", LABELS)

    draft = choose(funnel(radius=1), {}, lines=lines)

    assert (draft, draft.decision) == (core.EMPTY_ADVICE, "silent")


def test_stored_draft_has_no_text_or_people():
    draft = choose(funnel(disqualify=12), {"t2": sim(5, lines=[OWN]), "t3": sim(7, lines=[OTHER])})

    for secret in (OWN_TEXT, OTHER_TEXT, "u1", "u2"):
        assert secret not in str(draft)


# ---------------------------------------------------------------- 렌더

def _row(kind, claims, advice, actions=()):
    return SimpleNamespace(kind=kind, claims=claims, advice=advice, actions=list(actions))


def test_render_fills_claim_values():
    draft = choose(funnel(disqualify=12), {"t2": sim(5, lines=[OWN])})

    rendered = core.render_run_advice(RUN, _row(draft.kind, draft.claims, draft.advice, draft.actions))

    assert rendered.model_dump(mode="json") == {
        "run_id": RUN, "kind": "soft_relax",
        # 숫자와 줄 이름은 claim 슬롯이라 text 조각 하나다(#717)
        "advice": [{"segments": [{"kind": "text", "text": "「넓은 곳 원함」 조건을 빼면 5곳이 더 남아요."}], "is_guess": False}],
        "actions": [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                     "params": {"run_id": RUN, "evidence_line_ids": [OWN]}}],
    }


def test_render_empty_advice_is_none():
    assert core.render_run_advice(RUN, _row(None, [], [])) is None
    assert core.render_run_advice(RUN, None) is None
    # 렌더 결과에 금지 표현이 생기면 그 문장을 빼고, 남는 것이 없으면 None
    row = _row("exhausted", [{"id": "c1", "kind": "tool_result", "call_id": "t1", "path": "lines.0.label", "value": "확정하세요"}],
               [{"slot_text": "「{c1.value}」", "is_guess": False}])
    assert core.render_run_advice(RUN, row) is None

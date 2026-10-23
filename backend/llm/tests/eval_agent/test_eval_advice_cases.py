"""추천 막힘 조언 평가셋(#588)이 지금 규칙과 맞는지 — 모델 없이 본다(기본 테스트에 들어간다).

조언 평가는 run_eval.py --target advice가 실제 모델로 한다. 여기서는 평가셋이 대상 판정(run_advice_target), 근거 줄 종류
(evidence_kind), 버튼 규칙(verify_run_advice: 반경은 버튼 한 번의 배율, open_evidence는 본인 줄만)과 어긋나지 않는지 본다.
케이스마다 기대대로 쓴 모범 답을 만들어 운영 검증을 통과하는지 보므로, agent 규칙이 바뀌어 기대값이 낡으면 여기서 먼저 깨진다.
지시문 케이스(#717)는 진단과 같이 expect.decision_phrases로 결정 지시를 판정한다.
"""

import json

import pytest

from agent import core
from agent.schemas import Action, AdviceLine, RunAdviceOutput, ToolClaim
from llm.prompts import ADVICE_CLEAR_DROP, AGENT_ADVISE_RUN_PROMPT
from llm.tests.eval_agent import fixtures as fx
from llm.tests.eval_agent import fixtures_advice as fxa
from recommend import api as recommend_api

CASES = fxa.load_cases()
SUGGEST = [c for c in CASES if c["expect"]["decision"] == "suggest"]


def _by_id(prefix):
    return next(c for c in CASES if c["id"].startswith(prefix))


def _tc(cid, call_id, path, value):
    return ToolClaim(id=cid, kind="tool_result", call_id=call_id, path=path, value=value)


def _line_index(evidence, line_id):
    return next(i for i, line in enumerate(evidence["lines"]) if line["line_id"] == line_id)


def _reference(world, ctx, *, radius_factor=None, extra_actions=()):
    """기대(kinds의 첫째, mention, button_lines)대로 쓴 모범 답. 도구는 ctx로 실제로 부른다(call_id t1, t2 …)."""
    expect = world.case["expect"]
    kind = expect["kinds"][0]
    claims, advice, actions = [], [], []
    calls = iter(f"t{i}" for i in range(1, 10))

    def claim(call_id, path, value):
        claims.append(_tc(f"c{len(claims) + 1}", call_id, path, value))
        return claims[-1].id

    if kind == "radius":
        call_id = next(calls)
        factor = radius_factor or core.run_radius(world.meta)["next_radius_factor"]
        sim = ctx.run(call_id, "simulate_filter", {"radius_factor": factor, "disable_line_ids": None})
        gained = claim(call_id, "gained", sim["gained"])
        advice.append(AdviceLine(text=f"반경을 한 번 넓히면 {{{gained}.value}}곳이 더 남아요.", basis=[gained], is_guess=False))
        actions.append(Action(type="widen_radius", basis=[gained]))
    elif kind == "exhausted":
        stage = next(i for i, e in enumerate(ctx.results["t0"]["funnel"]) if e["label"] == fxa.EXCLUDED_STAGE)
        removed = claim("t0", f"funnel.{stage}.removed_count", ctx.results["t0"]["funnel"][stage]["removed_count"])
        advice.append(AdviceLine(text=f"이미 보여 드렸거나 거절한 곳 {{{removed}.value}}곳은 다시 추천하지 않아요.",
                                 basis=[removed], is_guess=False))
    else:
        ev_call = next(calls)
        evidence = ctx.run(ev_call, "get_run_evidence", {})
        for local in expect["mention"]:
            line_id = world.line_id(local)
            index = _line_index(evidence, line_id)
            own = evidence["lines"][index]["author"] == core.ADVICE_SELF
            if kind == "soft_relax":
                call_id = next(calls)
                sim = ctx.run(call_id, "simulate_filter", {"radius_factor": None, "disable_line_ids": [line_id]})
                label = claim(ev_call, f"lines.{index}.label", evidence["lines"][index]["label"])
                gained = claim(call_id, "gained", sim["gained"])
                advice.append(AdviceLine(text=f"「{{{label}.value}}」 조건 때문에 {{{gained}.value}}곳이 빠졌어요.",
                                         basis=[label, gained], is_guess=False))
                basis = gained
            else:
                basis = claim(ev_call, f"lines.{index}.line_id", line_id)
                advice.append(AdviceLine(text="적어 주신 근거 중 조건으로 읽히지 않아 추천에 반영되지 않은 글이 있어요.",
                                         basis=[basis], is_guess=False))
            if own:
                actions.append(Action(type="open_evidence", basis=[basis]))
    return RunAdviceOutput(decision="suggest", kind=kind, claims=claims, advice=advice, actions=actions + list(extra_actions))


def _run_reference(case, **kw):
    world = fxa.build(case)
    with fxa.patched_recommend_api([world]):
        ctx = world.tool_context()
        world.advice_input(ctx)
        out = _reference(world, ctx, **kw)
        return world, world.verify(out, ctx)


def _kept(draft):
    types = sorted(a["type"] for a in draft.actions)
    lines = {i for a in draft.actions for i in a["params"].get("evidence_line_ids", [])}
    return types, lines


# ---------------------------------------------------------------- 평가셋 구성


def test_cases_cover_kinds_buttons_and_silence():
    assert len(CASES) >= 20 and len({c["id"] for c in CASES}) == len(CASES)
    kinds = [c["expect"]["kinds"][0] for c in SUGGEST]
    for kind in ("radius", "soft_relax", "vague_reason", "exhausted"):
        assert kinds.count(kind) >= 2, kind
    assert sum(c["expect"]["decision"] == "silent" for c in CASES) >= 3
    # 다른 구성원 줄을 말하고 버튼은 없는 케이스(soft_relax, vague_reason)
    others = [c for c in SUGGEST if c["expect"]["kinds"][0] in ("soft_relax", "vague_reason") and not c["expect"]["buttons"]]
    assert {c["expect"]["kinds"][0] for c in others} == {"soft_relax", "vague_reason"}
    # 이미 상한이라 반경 버튼이 없는 케이스, 지시문 케이스, 알러지·가격 케이스
    assert sum(c["walk_min"] >= fxa.WIDEN_LIMIT_MIN for c in CASES) >= 2
    assert sum(any("지시" in (l.get("text") or "") or "AI에게" in (l.get("text") or "") for l in c["lines"]) for c in CASES) >= 2
    assert sum(any(l["kind"] == "not_filtered" for l in c["lines"]) for c in CASES) >= 2


def test_expected_fields_are_consistent():
    for case in CASES:
        e = case["expect"]
        locals_ = {l["id"] for l in case["lines"]}
        if e["decision"] == "silent":
            assert e["kinds"] == [] and e["buttons"] == [], case["id"]
        else:
            assert set(e["buttons"]) <= set(core.RUN_ADVICE_ACTIONS[e["kinds"][0]]), case["id"]
        assert set(e.get("button_lines", [])) <= set(e.get("mention", [])) <= locals_, case["id"]
        assert ("open_evidence" in e["buttons"]) == bool(e.get("button_lines")), case["id"]


# ---------------------------------------------------------------- 지금 규칙과 맞는지


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_case_is_an_advice_target(case):
    assert fxa.build(case).is_target


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_line_kinds_follow_evidence_kind(case):
    world = fxa.build(case)

    for raw, line in zip(case["lines"], world.lines):
        assert core.evidence_kind(line) == raw["kind"], (case["id"], raw["id"])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_simulation_numbers_are_consistent(case):
    """끄면 늘어나는 줄은 켜져 있는 실격 조건 줄뿐이고, 늘어나는 수는 그 단계에서 빠진 수를 넘지 않는다. 반경도 같다."""
    funnel = dict(case["funnel"])
    for raw in case["lines"]:
        if raw.get("gain", 0) > 0:
            assert raw["kind"] == "condition" and raw.get("active", True) and raw.get("badge", "required") == "required"
    assert sum(raw.get("gain", 0) for raw in case["lines"]) <= funnel.get(fxa.DISQUALIFY_STAGE, 0)
    gains = {int(k): v for k, v in case.get("radius_gain", {}).items()}
    assert max(gains.values(), default=0) <= funnel.get(fxa.RADIUS_STAGE, 0)
    assert all(case["walk_min"] < minutes <= fxa.WIDEN_LIMIT_MIN for minutes in gains)


@pytest.mark.parametrize("case", SUGGEST, ids=[c["id"] for c in SUGGEST])
def test_reference_answer_passes_with_expected_buttons(case):
    world, verified = _run_reference(case)

    assert verified.outcome == "advised", verified.record
    types, lines = _kept(verified.draft)
    assert set(types) == set(case["expect"]["buttons"])
    assert lines == {world.line_id(i) for i in case["expect"].get("button_lines", [])}
    rendered = world.render(verified.draft)
    assert rendered is not None and rendered.advice


RADIUS_STEPS = [c for c in SUGGEST if c["expect"]["kinds"][0] == "radius"
                and core.run_radius(fxa.build(c).meta)["next_radius_factor"] != core.run_radius(fxa.build(c).meta)["max_radius_factor"]]


@pytest.mark.parametrize("case", RADIUS_STEPS, ids=[c["id"] for c in RADIUS_STEPS])
def test_widen_button_is_removed_for_the_limit_simulation(case):
    """상한까지 넓힌 숫자에는 버튼이 붙지 않는다(#677, not_next_step). 문장은 사실이라 남는다."""
    max_factor = core.run_radius(fxa.build(case).meta)["max_radius_factor"]

    _, verified = _run_reference(case, radius_factor=max_factor)

    assert verified.outcome == "advised"
    assert verified.draft.actions == []
    assert verified.record["actions"]["removed"] == [{"index": 0, "reason": "not_next_step"}]


OTHER_MENTIONED = [c for c in SUGGEST if c["expect"]["kinds"][0] in ("soft_relax", "vague_reason")
                   and set(c["expect"]["mention"]) - set(c["expect"].get("button_lines", []))]


@pytest.mark.parametrize("case", OTHER_MENTIONED, ids=[c["id"] for c in OTHER_MENTIONED])
def test_button_on_another_members_line_is_removed(case):
    """다른 구성원 줄을 가리키는 open_evidence는 검증이 뺀다(not_own_line). 기대 버튼(본인 줄)은 그대로 남는다."""
    other = sorted(set(case["expect"]["mention"]) - set(case["expect"].get("button_lines", [])))[0]
    index = case["expect"]["mention"].index(other)
    per_line = 2 if case["expect"]["kinds"][0] == "soft_relax" else 1   # soft_relax는 줄마다 label, gained
    claim_id = f"c{(index + 1) * per_line}"

    world, verified = _run_reference(case, extra_actions=[Action(type="open_evidence", basis=[claim_id])])

    assert [r["reason"] for r in verified.record["actions"]["removed"]] == ["not_own_line"]
    _, lines = _kept(verified.draft)
    assert lines == {world.line_id(i) for i in case["expect"].get("button_lines", [])}


def _procedure_kind(world):
    """프롬프트 「종류(kind) 고르기」 순서를 케이스 데이터에 그대로 적용한 종류. 침묵이면 None."""
    stages = {e["label"]: e["removed_count"] for e in world.funnel["funnel"]}
    next_factor = core.run_radius(world.meta)["next_radius_factor"]
    for label in sorted((fxa.RADIUS_STAGE, fxa.DISQUALIFY_STAGE, fxa.EXCLUDED_STAGE), key=lambda s: -stages[s]):
        if stages[label] < ADVICE_CLEAR_DROP:
            continue
        if label == fxa.RADIUS_STAGE:
            if next_factor is not None and world.simulate(next_factor, ())["after"]["passed_count"] > world.funnel["passed_count"]:
                return "radius"
        elif label == fxa.DISQUALIFY_STAGE:
            if any(world.gains[line["line_id"]] > 0 for line in world.lines):
                return "soft_relax"
        else:
            return "exhausted"
    return "vague_reason" if any(core.evidence_kind(line) == "vague" for line in world.lines) else None


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_expected_kind_follows_the_prompt_procedure(case):
    """기대 종류가 프롬프트의 고르는 순서(뚜렷한 탈락 ADVICE_CLEAR_DROP)와 같다 — 평가셋과 프롬프트가 같은 규칙을 본다."""
    kind = _procedure_kind(fxa.build(case))

    assert kind == (case["expect"]["kinds"][0] if case["expect"]["decision"] == "suggest" else None)


def test_radius_at_limit_has_no_next_step():
    for case in (c for c in CASES if c["walk_min"] >= fxa.WIDEN_LIMIT_MIN):
        assert core.run_radius(fxa.build(case).meta)["next_radius_factor"] is None
        assert "radius" not in case["expect"]["kinds"]


# ---------------------------------------------------------------- 입력과 도구 모양


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_advice_input_has_no_evidence_text_and_names_the_prompt_fields(case):
    world = fxa.build(case)
    with fxa.patched_recommend_api([world]):
        inp = world.advice_input(world.tool_context())

    dumped = json.dumps(inp, ensure_ascii=False, default=str)
    for line in world.lines:   # 근거 글은 입력에 없다(get_run_evidence로만 읽는다)
        assert not line["text"] or line["text"] not in dumped
    for key in inp["radius"]:   # 프롬프트가 설명하는 칸과 agent가 넣는 칸이 같다
        assert key in AGENT_ADVISE_RUN_PROMPT
    assert inp["funnel"]["call_id"] == core.PREFETCH_CALL_ID


def test_fixture_tools_run_through_run_tool_context():
    world = fxa.build(_by_id("a07"))
    own, other = world.line_id("l2"), world.line_id("l1")
    with fxa.patched_recommend_api([world]):
        ctx = world.tool_context()
        funnel = ctx.prefetch(core.PREFETCH_CALL_ID, "get_run_funnel")
        evidence = ctx.run("t1", "get_run_evidence", {})
        sim = ctx.run("t2", "simulate_filter", {"radius_factor": None, "disable_line_ids": [own]})
        widen = ctx.run("t3", "simulate_filter", {"radius_factor": 25 / 20, "disable_line_ids": None})
        unknown = ctx.run("t4", "simulate_filter", {"radius_factor": None, "disable_line_ids": ["no-such-line"]})
        zero = ctx.run("t5", "simulate_filter", {"radius_factor": 0, "disable_line_ids": None})

    assert funnel == {"result_count": 1, "funnel": [{"label": s, "removed_count": dict(world.case["funnel"]).get(s, 0)}
                                                     for s in fxa.STAGES], "passed": 1}
    assert [(l["line_id"], l["author"], l["kind"]) for l in evidence["lines"]] == [
        (other, core.ADVICE_OTHER, "condition"), (own, core.ADVICE_SELF, "condition")]
    assert evidence["lines"][0]["label"] == f"{recommend_api.fact_labels()['oily_focused']} 제외" and evidence["total"] == 2
    assert (sim["gained"], sim["before"], sim["after"]["passed"]) == (6, funnel, 7)
    assert (widen["gained"], widen["within_widen_limit"]) == (0, True)
    assert unknown == zero == {"error": "NOT_FOUND"}
    assert ctx.names == {"t0": "get_run_funnel", "t1": "get_run_evidence", "t2": "simulate_filter", "t3": "simulate_filter",
                         "t4": "simulate_filter", "t5": "simulate_filter"}
    stored = json.dumps(ctx.calls, ensure_ascii=False)   # 저장용 기록에는 근거 글 대신 글자 수
    assert "느끼한 건 별로예요" not in stored and "text_len" in stored


def test_not_filtered_lines_carry_no_text():
    world = fxa.build(_by_id("a21"))
    with fxa.patched_recommend_api([world]):
        evidence = world.tool_context().run("t1", "get_run_evidence", {})

    kinds = {l["line_id"]: (l["kind"], l["text"]) for l in evidence["lines"]}
    assert kinds[world.line_id("l1")] == ("not_filtered", None)   # 알러지 글은 도구 결과에도 없다
    assert kinds[world.line_id("l2")] == ("not_filtered", None)


# ---------------------------------------------------------------- 지시문 케이스와 결정 지시 판정 (#717)

INJECTION_CASES = [c for c in CASES if c["expect"].get("decision_phrases")]
NEW_EXPRESSION_CASES = [c for c in INJECTION_CASES if c["id"][:3] in ("a24", "a25")]


def _injected(case):
    phrases = case["expect"]["decision_phrases"]
    return [l["text"] for l in case["lines"] if fx.decision_echoes([l.get("text") or ""], phrases)]


def test_injection_cases_cover_own_and_other_lines():
    by = {l["by"] for c in NEW_EXPRESSION_CASES for l in c["lines"] if l.get("text") in _injected(c)}

    assert len(NEW_EXPRESSION_CASES) == 2 and by == {"self", "other"}


@pytest.mark.parametrize("case", INJECTION_CASES, ids=[c["id"] for c in INJECTION_CASES])
def test_decision_phrases_come_from_the_injected_line(case):
    assert _injected(case)


@pytest.mark.parametrize("case", NEW_EXPRESSION_CASES, ids=[c["id"] for c in NEW_EXPRESSION_CASES])
def test_new_injection_expressions_pass_the_forbidden_list(case):
    """#717에서 더한 지시문은 금지어 목록(core.FORBIDDEN_PHRASES)에 걸리지 않는다 — 목록 밖 표현을 재려는 케이스다."""
    assert fx.decision_echoes(_injected(case), core.FORBIDDEN_PHRASES) == []


@pytest.mark.parametrize("case", INJECTION_CASES, ids=[c["id"] for c in INJECTION_CASES])
def test_reference_answer_renders_text_segments_without_decision_phrases(case):
    """모범 답의 렌더(text 조각만)에는 케이스 문구가 없다 — 평가 러너가 세는 길(world.render → 조각)이 조각 모양으로 돈다."""
    world, verified = _run_reference(case)
    rendered = world.render(verified.draft)
    segments = [[s.model_dump() for s in line.segments] for line in rendered.advice]

    assert {s["kind"] for line in segments for s in line} == {"text"}
    assert fx.decision_echoes((fx.segment_texts(line) for line in segments), case["expect"]["decision_phrases"]) == []

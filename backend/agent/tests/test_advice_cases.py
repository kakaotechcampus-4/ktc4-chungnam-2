"""추천 막힘 조언 회귀 셋 25건(#588 평가셋, #750에서 옮김) — 코드 절차(core.choose_run_advice)가 케이스의 기대와 같은지.

평가셋은 모델(advise-v4)에 기대한 답을 적은 것이다. 모델을 뺀 뒤(#749)에는 같은 기대를 코드가 지키는지 본다: decision, 종류
(kinds의 첫째), 버튼 종류, 버튼이 가리키는 줄(본인 줄만), 문장이 말하는 줄(mention). 지시문 케이스는 근거 글의 지시가 결과를
바꾸지 않고 응답에 옮겨지지 않는지 본다. DB 없이 돈다.
"""

import re

import pytest

from agent import core
from agent.constants import ADVICE_CLEAR_DROP
from agent.tests import fixtures_advice as fxa
from recommend import api as recommend_api

CASES = fxa.load_cases()
SUGGEST = [c for c in CASES if c["expect"]["decision"] == "suggest"]
BUTTONS = {"radius": {"widen_radius"}, "soft_relax": {"open_evidence"}, "vague_reason": {"open_evidence"}, "exhausted": set()}


def _by_id(prefix):
    return next(c for c in CASES if c["id"].startswith(prefix))


def _button_lines(draft):
    return {i for a in draft.actions for i in a["params"].get("evidence_line_ids", [])}


def _mentioned_lines(world, draft):
    """문장이 가리키는 근거 줄 — 근거 줄 claim(lines.N.label, lines.N.line_id)의 N."""
    return {world.lines[int(c["path"].split(".")[1])]["line_id"]
            for c in draft.claims if c["call_id"] == core.EVIDENCE_CALL_ID}


_SPACES = re.compile(r"\s+")


def _echoes(texts, phrases):
    """글에 나온 결정 지시 문구(#717). 공백을 빼고 비교한다."""
    said = _SPACES.sub("", " ".join(texts))
    return [p for p in phrases if _SPACES.sub("", p) in said]


# ---------------------------------------------------------------- 셋 구성


def test_cases_cover_kinds_buttons_and_silence():
    assert len(CASES) == 25 and len({c["id"] for c in CASES}) == len(CASES)
    kinds = [c["expect"]["kinds"][0] for c in SUGGEST]
    for kind in BUTTONS:
        assert kinds.count(kind) >= 2, kind
    assert sum(c["expect"]["decision"] == "silent" for c in CASES) >= 3
    # 다른 구성원 줄을 말하고 버튼은 없는 케이스(soft_relax, vague_reason)
    others = [c for c in SUGGEST if c["expect"]["kinds"][0] in ("soft_relax", "vague_reason") and not c["expect"]["buttons"]]
    assert {c["expect"]["kinds"][0] for c in others} == {"soft_relax", "vague_reason"}
    # 이미 상한이라 반경 버튼이 없는 케이스, 지시문 케이스, 알러지·가격 케이스
    assert sum(c["walk_min"] >= fxa.WIDEN_LIMIT_MIN for c in CASES) >= 2
    assert sum(bool(c["expect"].get("decision_phrases")) for c in CASES) >= 2
    assert sum(any(line["kind"] == "not_filtered" for line in c["lines"]) for c in CASES) >= 2


def test_expected_fields_are_consistent():
    for case in CASES:
        e = case["expect"]
        locals_ = {line["id"] for line in case["lines"]}
        if e["decision"] == "silent":
            assert e["kinds"] == [] and e["buttons"] == [], case["id"]
        else:
            assert set(e["buttons"]) <= BUTTONS[e["kinds"][0]], case["id"]
        assert set(e.get("button_lines", [])) <= set(e.get("mention", [])) <= locals_, case["id"]
        assert ("open_evidence" in e["buttons"]) == bool(e.get("button_lines")), case["id"]


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
    assert sum(raw.get("gain", 0) for raw in case["lines"]) <= funnel.get(core.DISQUALIFY_STAGE, 0)
    gains = {int(k): v for k, v in case.get("radius_gain", {}).items()}
    assert max(gains.values(), default=0) <= funnel.get(core.RADIUS_STAGE, 0)
    assert all(case["walk_min"] < minutes <= fxa.WIDEN_LIMIT_MIN for minutes in gains)


# ---------------------------------------------------------------- 코드 판정 = 기대


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_code_decides_as_expected(case):
    world = fxa.build(case)
    e = case["expect"]

    draft, _ = world.advise()

    assert draft.decision == ("advise" if e["decision"] == "suggest" else "silent")
    assert draft.kind == (e["kinds"][0] if e["kinds"] else None)
    assert {a["type"] for a in draft.actions} == set(e["buttons"])
    assert _button_lines(draft) == {world.line_id(i) for i in e.get("button_lines", [])}
    if draft.kind in ("soft_relax", "vague_reason"):
        assert _mentioned_lines(world, draft) == {world.line_id(i) for i in e["mention"]}


@pytest.mark.parametrize("case", SUGGEST, ids=[c["id"] for c in SUGGEST])
def test_buttons_point_only_at_the_requesters_own_lines(case):
    """open_evidence는 본인 줄만 가리킨다 — 근거 줄 빼기는 쓴 사람만 할 수 있다(9절). 버튼은 종류마다 많아야 하나다."""
    world = fxa.build(case)

    draft, _ = world.advise()

    assert all(world.own(i) for i in _button_lines(draft))
    assert len(draft.actions) <= 1


@pytest.mark.parametrize("case", SUGGEST, ids=[c["id"] for c in SUGGEST])
def test_rendered_advice_is_fixed_text_with_numbers_only_from_claims(case):
    world = fxa.build(case)
    draft, _ = world.advise()

    rendered = world.render(draft)

    assert rendered is not None and rendered.kind == draft.kind and rendered.advice
    segments = [s for line in rendered.advice for s in line.segments]
    assert {s.kind for s in segments} == {"text"}   # 근거 글 인용이나 핀 이름 조각이 없다(#717)
    said = " ".join(s.text for s in segments)
    assert not re.search(r"\d", re.sub(r"\{c\d+\.value\}", "", " ".join(a["slot_text"] for a in draft.advice)))
    for line in world.lines:   # 근거 글은 문장에도 저장에도 없다(2절 11번, 13번)
        assert line["text"] not in said and line["text"] not in str(draft)
    assert "본인" not in said and "다른 구성원" not in said   # 누가 쓴 조건인지 쓰지 않는다


def test_radius_says_the_one_press_number_not_the_limit():
    """버튼 한 번(15→20분)이면 3곳, 상한(30분)이면 12곳. 버튼을 눌렀을 때와 같은 숫자만 말한다(#677)."""
    world = fxa.build(_by_id("a01"))

    draft, wanted = world.advise()

    assert list(wanted.values()) == [{"radius_factor": 20 / 15, "disable_line_ids": []}]
    assert [c["value"] for c in draft.claims] == [3]
    assert draft.actions == [{"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": world.run_id}}]
    assert world.render(draft).advice[0].segments[0].text == "반경 넓히기를 한 번 누르면 3곳이 더 남아요."


def test_radius_at_limit_has_no_next_step():
    for case in (c for c in CASES if c["walk_min"] >= fxa.WIDEN_LIMIT_MIN):
        world = fxa.build(case)
        assert core.next_radius_factor(world.meta) is None
        assert all(args["radius_factor"] is None for args in world.advise()[1].values())


@pytest.mark.parametrize("prefix", ["a14", "a15", "a20"])
def test_exhausted_first_needs_no_simulation(prefix):
    """「이미 제안·거절됨」이 가장 많이 빠진 단계면 시뮬레이션을 돌리지 않는다 — 필요한 것만 부른다."""
    draft, wanted = fxa.build(_by_id(prefix)).advise()

    assert (draft.kind, wanted) == ("exhausted", {})


def test_soft_relax_simulates_each_relaxable_line_once():
    """반경 단계가 작으면(ADVICE_CLEAR_DROP 미만) 반경은 시뮬레이션하지 않고, 조건 줄은 켜진 줄만 하나씩 끈다."""
    world = fxa.build(_by_id("a08"))
    assert dict(world.case["funnel"])[core.RADIUS_STAGE] < ADVICE_CLEAR_DROP

    _, wanted = world.advise()

    assert [args["disable_line_ids"] for args in wanted.values()] == [[world.line_id("l2")], [world.line_id("l3")]]


def test_soft_relax_sentences():
    """a07: 다른 구성원 줄(9곳)이 본인 줄(6곳)보다 많이 걸렀다 — 둘 다 말하고 버튼은 본인 줄에만. 누가 썼는지는 쓰지 않는다."""
    world = fxa.build(_by_id("a07"))
    labels = recommend_api.fact_labels()

    draft, _ = world.advise()

    assert [line.segments[0].text for line in world.render(draft).advice] == [
        f"「{labels['oily_focused']} 제외」 조건을 빼면 9곳이 더 남아요.",
        f"「{labels['wait_short']} 원함」 조건을 빼면 6곳이 더 남아요.",
    ]
    assert draft.actions == [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
                              "params": {"run_id": world.run_id, "evidence_line_ids": [world.line_id("l2")]}}]


@pytest.mark.parametrize("prefix, own", [("a10", True), ("a11", False)])
def test_vague_reason_sentences(prefix, own):
    world = fxa.build(_by_id(prefix))

    draft, _ = world.advise()
    rendered = world.render(draft)

    assert [(line.segments[0].text, line.is_guess) for line in rendered.advice] == [
        ("조건으로 읽지 못한 글이 있어 추천에 반영되지 않았어요.", False),
        ("'조용한 곳이 좋아요'처럼 원하는 점을 적으면 반영돼요.", True),
    ]
    assert [a.label for a in rendered.actions] == (["근거 확인하기"] if own else [])


def test_exhausted_sentence():
    world = fxa.build(_by_id("a14"))

    rendered = world.render(world.advise()[0])

    assert [line.segments[0].text for line in rendered.advice] == ["이미 보여 줬거나 거절한 18곳은 다시 추천하지 않아요."]
    assert rendered.actions == []


# ---------------------------------------------------------------- 지시문 케이스 (#717)

INJECTION_CASES = [c for c in CASES if c["expect"].get("decision_phrases") or any(
    "AI에게" in (line.get("text") or "") for line in c["lines"])]


def _injected(case):
    phrases = case["expect"].get("decision_phrases") or ["AI에게"]
    return [line["id"] for line in case["lines"] if _echoes([line.get("text") or ""], phrases)]


def test_injection_cases_cover_own_and_other_lines():
    by = {line["by"] for c in INJECTION_CASES for line in c["lines"] if line["id"] in _injected(c)}

    assert len(INJECTION_CASES) >= 2 and by == {"self", "other"}


@pytest.mark.parametrize("case", INJECTION_CASES, ids=[c["id"] for c in INJECTION_CASES])
def test_instructions_in_evidence_text_do_not_change_the_advice(case):
    """근거 글의 지시(확정하라, 반경 버튼을 붙여라, 다른 데는 보지 마)를 지운 글로 바꿔도 조언이 같다 — 절차는 글을 읽지 않는다.
    응답 문장에도 지시 문구가 옮겨지지 않는다."""
    plain = {**case, "lines": [{**line, "text": "그냥 그래요"} if line["id"] in _injected(case) else line
                               for line in case["lines"]]}
    world = fxa.build(case)

    draft, wanted = world.advise()

    assert (draft, wanted) == fxa.build(plain).advise()
    rendered = world.render(draft)
    said = [s.text for line in rendered.advice for s in line.segments]
    assert _echoes(said, case["expect"].get("decision_phrases", ["이십", "최대로"])) == []

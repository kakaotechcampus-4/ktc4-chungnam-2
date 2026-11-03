"""우리 데이터 확인(명세 6.6, #1168) — 사실 다툼의 (핀, 키) 고르기와 고정 문구 렌더. 순수 함수, 모델 없음.

- 갈림: 같은 키·같은 방향(사실 다툼)만 붙고, 방향이 반대(취향 다툼)거나 키가 다르면 붙지 않는다
- 정체: 🚫 사유의 키(칩·글)
- 실시간 핀 제외, 많아야 2줄, 참·거짓·모름 문구, 라벨이 바뀌면 렌더가 바뀐다, 저장에는 (pin_id, fact_key)만
"""

from dataclasses import replace

import pytest

from agent import core
from agent.snapshot import Pin
from agent.tests.snaps import NOW, hours, pin, react, snap

LABELS = {"quiet": "조용한 곳", "parking_available": "주차 가능", "spicy_focused": "매운맛 전문", "wait_short": "대기가 짧은 곳"}


def _structured(rid, type_, *keys):
    """structure_reasons 모양 한 줄 — keys는 (fact_key, wants)."""
    return {"reaction_id": rid, "type": type_,
            "lines": [{"fact_key": k, "wants": w, "badge": "required"} for k, w in keys]}


def _split(pin_id="p1"):
    return core.make_signal("split", category="음식점", pin_id=pin_id,
                            evidence=[("r1", "like", NOW), ("r2", "against", NOW)], features={})


def _stall(*reaction_ids):
    return core.make_signal("stall", category="음식점", evidence=[(r, "against", NOW) for r in reaction_ids],
                            features={})


def _live(pin_id):
    return Pin(pin_id=pin_id, category="음식점", source="live", place_id=None, search_query="성수 칼국수",
               created_by="u1", created_at=NOW - hours(100))


# ---------------------------------------------------------------- 갈림: 사실 다툼과 취향 다툼

def test_split_same_key_same_direction_is_a_fact_dispute():
    """♥ "조용해서 좋아요"(quiet 원함)와 🚫 「시끄러워요」(quiet 원함) — 이 가게가 조용한지를 두고 갈렸다(6.3 표 마지막 줄)."""
    comparison = core.compare_reasons([_structured("r1", "like", ("quiet", True)),
                                       _structured("r2", "against", ("quiet", True))])
    assert comparison["conflict_type"] == "unclear"

    s = snap(pins=[pin("p1")])
    assert core.fact_targets(_split(), s, comparison=comparison) == [{"pin_id": "p1", "fact_key": "quiet"}]


@pytest.mark.parametrize("like, against, conflict", [
    (("quiet", True), ("quiet", False), "same_axis"),            # 취향이 갈렸다 — 데이터로 풀 일이 아니다
    (("quiet", True), ("parking_available", True), "different_axes"),
])
def test_split_taste_or_different_axes_gets_no_fact_line(like, against, conflict):
    comparison = core.compare_reasons([_structured("r1", "like", like), _structured("r2", "against", against)])
    assert comparison["conflict_type"] == conflict

    assert core.fact_targets(_split(), snap(pins=[pin("p1")]), comparison=comparison) == []


def test_split_without_comparison_gets_nothing():
    """②가 실패해 충돌 분석이 없으면 칸을 붙이지 않는다."""
    assert core.fact_targets(_split(), snap(pins=[pin("p1")]), comparison=None) == []


def test_split_unclear_with_shared_key_but_no_direction_gets_nothing():
    comparison = core.compare_reasons([_structured("r1", "like", ("quiet", None)),
                                       _structured("r2", "against", ("quiet", None))])
    assert comparison["conflict_type"] == "unclear"
    assert core.fact_targets(_split(), snap(pins=[pin("p1")]), comparison=comparison) == []


# ---------------------------------------------------------------- 정체: 반대 사유의 키

def _stall_snap(*pins_):
    rs = [react("r1", "p1", "u2", "against", NOW - hours(20)), react("r2", "p2", "u3", "against", NOW - hours(19)),
          react("r3", "p2", "u1", "against", NOW - hours(18))]
    return snap(pins=pins_ or [pin("p1"), pin("p2")], reactions=rs)


def test_stall_takes_keys_from_against_reasons_most_mentioned_first():
    against = [
        _structured("r1", "against", ("spicy_focused", False)),
        _structured("r2", "against", ("parking_available", True)),
        _structured("r3", "against", ("parking_available", True), ("wait_short", True)),
    ]

    got = core.fact_targets(_stall("r1", "r2", "r3"), _stall_snap(), against=against)

    # 주차는 🚫 둘이 말했다 → 먼저. 나머지 하나씩은 키 이름 순(초안)
    assert got == [{"pin_id": "p2", "fact_key": "parking_available"}, {"pin_id": "p1", "fact_key": "spicy_focused"}]


def test_at_most_two_lines():
    against = [_structured("r1", "against", ("spicy_focused", False), ("quiet", True), ("wait_short", True))]

    assert len(core.fact_targets(_stall("r1", "r2", "r3"), _stall_snap(), against=against)) == 2


def test_stall_ignores_reasons_outside_the_signal_and_keyless_lines():
    against = [_structured("r1", "against", (None, None)), _structured("rX", "against", ("quiet", True)),
               _structured("r2", "like", ("quiet", True))]

    assert core.fact_targets(_stall("r1", "r2", "r3"), _stall_snap(), against=against) == []


def test_live_pin_is_excluded():
    """실시간 핀은 자체 DB 장소가 없어 라벨이 없다(#382)."""
    against = [_structured("r1", "against", ("spicy_focused", False)),
               _structured("r2", "against", ("parking_available", True))]

    got = core.fact_targets(_stall("r1", "r2", "r3"), _stall_snap(pin("p1"), _live("p2")), against=against)

    assert got == [{"pin_id": "p1", "fact_key": "spicy_focused"}]


@pytest.mark.parametrize("diagnosis", ["no_reaction", "category_gap"])
def test_code_types_get_nothing(diagnosis):
    sig = core.make_signal(diagnosis, category="카페", evidence=[("p1", "pin", NOW)], features={})
    against = [_structured("r1", "against", ("quiet", True))]
    assert core.fact_targets(sig, snap(pins=[pin("p1")]), against=against) == []


def test_stored_targets_have_only_pin_and_key():
    """저장에는 (pin_id, fact_key)만 — 사유 글, 라벨 값, 핀 이름이 없다(2절 13번, 6.6)."""
    against = [_structured("r1", "against", ("spicy_focused", False))]
    [target] = core.fact_targets(_stall("r1", "r2", "r3"), _stall_snap(), against=against)
    assert set(target) == {"pin_id", "fact_key"}


# ---------------------------------------------------------------- 렌더: 참·거짓·모름 고정 문구

def _refs(values, *, names=None, labels=LABELS):
    return core.RenderRefs(pin_names=names if names is not None else {"p1": "성수 칼국수", "p2": "카페 온도"},
                           fact_labels=labels, fact_values=values)


def _text(line):
    return "".join(seg.text for seg in line.segments)


@pytest.mark.parametrize("value, expected, text", [
    (True, "yes", "우리 데이터: 성수 칼국수는 주차 가능으로 나와요"),
    (False, "no", "우리 데이터: 성수 칼국수는 주차 가능이 아니라고 나와요. 데이터가 틀릴 수 있어요"),
    (None, "unknown", "우리 데이터로는 성수 칼국수가 주차 가능인지 몰라요"),
])
def test_fact_line_phrases(value, expected, text):
    [line] = core.render_fact_lines([{"pin_id": "p1", "fact_key": "parking_available"}],
                                    _refs({"p1": {"parking_available": value}}))

    assert (line.fact_key, line.value, _text(line)) == ("parking_available", expected, text)
    # 핀 이름은 pin 조각이다. 구성원 글(quote)은 없다
    assert [seg.kind for seg in line.segments] == ["text", "pin", "text"]
    assert line.segments[1].pin_id == "p1"


def test_no_label_row_is_unknown_and_false_never_concludes():
    """라벨이 없는 키는 모름이다(지어내지 않는다). 거짓에도 결론(「괜찮아요」)을 쓰지 않는다."""
    [unknown, no] = core.render_fact_lines(
        [{"pin_id": "p1", "fact_key": "quiet"}, {"pin_id": "p2", "fact_key": "spicy_focused"}],
        _refs({"p1": {}, "p2": {"spicy_focused": False}}))

    assert unknown.value == "unknown"
    assert _text(no) == "우리 데이터: 카페 온도는 매운맛 전문이 아니라고 나와요. 데이터가 틀릴 수 있어요"
    assert "괜찮" not in _text(no)


def test_label_change_changes_the_render():
    """저장된 것은 (pin_id, fact_key)뿐이라 라벨이 바뀌면 같은 제안의 화면도 바뀐다."""
    facts = [{"pin_id": "p1", "fact_key": "quiet"}]
    before = core.render_fact_lines(facts, _refs({"p1": {"quiet": None}}))
    after = core.render_fact_lines(facts, _refs({"p1": {"quiet": True}}))

    assert (before[0].value, after[0].value) == ("unknown", "yes")
    assert _text(after[0]) == "우리 데이터: 성수 칼국수는 조용한 곳으로 나와요"


def test_deleted_pin_or_unnamed_key_drops_the_line():
    facts = [{"pin_id": "gone", "fact_key": "quiet"}, {"pin_id": "p1", "fact_key": "no_such_key"}]
    assert core.render_fact_lines(facts, _refs({})) == []


@pytest.mark.parametrize("name, topic, subject", [
    ("성수 칼국수", "는", "가"),             # 받침 없음
    ("을지로 곱창", "은", "이"),             # 받침 있음
    ("스타벅스(성수점)", "은", "이"),        # 괄호 안의 끝 글자
    ("CAFE ABC", "은(는)", "이(가)"),       # 고를 수 없으면 함께
    ("카페 1", "은", "이"),                 # 숫자는 읽은 소리(일)
])
def test_particles_follow_the_pin_name(name, topic, subject):
    yes, unknown = (core.render_fact_lines([{"pin_id": "p1", "fact_key": "quiet"}],
                                           _refs({"p1": {"quiet": v}}, names={"p1": name}))[0] for v in (True, None))

    assert yes.segments[2].text.startswith(topic + " ")
    assert unknown.segments[2].text.startswith(subject + " ")


def test_suggestion_render_carries_fact_lines():
    draft = replace(core.render_template(core.make_signal("category_gap", category="카페",
                                                          evidence=[("p1", "pin", NOW)], features={})),
                    facts=[{"pin_id": "p1", "fact_key": "quiet"}])
    row = type("Row", (), dict(id="s", diagnosis="stall", category="카페", title=draft.title, claims=draft.claims,
                               analysis=None, advice=draft.advice, actions=draft.actions, facts=draft.facts,
                               created_at=NOW, expires_at=NOW + hours(24)))

    out = core.render_suggestion(row, _refs({"p1": {"quiet": True}}))

    assert [f.value for f in out.facts] == ["yes"]

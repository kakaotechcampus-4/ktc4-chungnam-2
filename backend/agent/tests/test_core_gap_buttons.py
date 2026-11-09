"""#1583 — 눌러도 할 수 있는 게 없는 버튼을 내지 않는다. 카테고리 공백은 추천 준비 상태로, 반응 공백은 화면이 쓰는 필터로 버튼을 정한다."""

import pytest

from agent import core
from agent.schemas import AgentAction
from agent.tests.snaps import NOW, hours, item, pin, snap

TWO = dict(shortlist=[item("f1"), item("f2")])


def _signals(*, ready=(), extra_pins=()):
    s = snap(pins=[pin("f1"), pin("f2"), *extra_pins], ready_categories=ready, **TWO)
    return {sig.category: sig for sig in core.detect_category_gap(s)}


def test_gap_state_follows_readiness_and_pins():
    sigs = _signals(ready=("카페",), extra_pins=[pin("c1", category="카페"), pin("t1", category="관광지")])
    assert {c: s.features["gap_state"] for c, s in sigs.items()} == {"카페": "ready", "관광지": "pins"}
    assert _signals()["카페"].features["gap_state"] == "empty"


@pytest.mark.parametrize("state, button", [
    ("ready", ("open_recommend", "카페 추천 받기", {"category": "카페"})),
    ("pins", ("show_pins", "카페 핀에 의견 남기기", {"category": "카페", "unseen_only": True})),
    ("empty", ("search_place", "카페 검색", {"category": "카페"})),
])
def test_category_gap_button_by_state(state, button):
    sig = _signals()["카페"]
    sig = core.replace(sig, features={**sig.features, "gap_state": state})
    [action] = core.render_template(sig).actions
    assert (action["type"], action["label"], action["params"]) == button
    AgentAction(**action)   # 스펙의 params 키만 쓴다


def test_not_ready_category_never_offers_recommend_and_skips_the_model():
    sigs = _signals(extra_pins=[pin("c1", category="카페")])
    cafe = sigs["카페"]
    assert cafe.features["candidate_pin_ids"] == ["c1"]
    assert core.uses_model(cafe) is False   # 의견이 없어 진단할 재료가 없다 — 템플릿으로 간다
    assert core.allowed_actions(cafe) == ("show_pins", "search_place")
    assert core.allowed_actions(sigs["관광지"]) == ("search_place",)

    ready = _signals(ready=("카페",), extra_pins=[pin("c1", category="카페")])["카페"]
    assert core.uses_model(ready) is True
    assert core.allowed_actions(ready) == ("open_pin", "open_recommend", "search_place")


def test_followup_after_opinion_button_falls_back_to_search():
    sig = _signals(extra_pins=[pin("c1", category="카페")])["카페"]
    tried = [{"action_type": "show_pins", "label": "카페 핀에 의견 남기기", "accepted_at": NOW.isoformat()}]
    follow = core.replace(sig, features={**sig.features, "attempt": 1, "tried": tried})
    assert core.allowed_actions(follow) == ("search_place",)
    [action] = core.render_followup_template(follow).actions
    assert (action["type"], action["label"]) == ("search_place", "카페 검색")


def test_no_reaction_button_carries_the_unseen_filter_the_screen_uses():
    sig = core.make_signal("no_reaction", category=None, evidence=[("p1", "pin", NOW - hours(5))], features={})
    [action] = core.render_template(sig).actions
    assert action["type"] == "show_pins"
    assert action["params"]["unseen_only"] is True and action["params"]["pin_ids"] == ["p1"]
    AgentAction(**action)

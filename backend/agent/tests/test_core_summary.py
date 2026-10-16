"""우리 조건 요약의 판단(명세 8절, #586) — 다섯 칸 나누기, 키 없는 사유 세 갈래, 갱신 조건, 렌더. DB 없이 core만 본다.

17절 2번(키 없는 사유: 알러지 낱말과 「비싸요」는 not_filtered, 「너무 멀어요」는 vague_fixable, 원문을 렌더하지 않음),
17번(#422로 선호가 된 음식 종류 "원함"은 must_keep이 아님, 같은 사람 같은 키는 1명). #422 분류 자체는 tools가 걸고
test_flows_summary.py가 끝까지 본다 — 여기서는 분류된 줄(preferred)이 어디로 가는지만 본다.
"""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from agent import core
from agent.tests.snaps import NOW, hours, member, pin, react, snap
from agent.snapshot import Chip, Reason

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))
LABELS = {"spicy_focused": "매운맛 전문", "quiet": "조용한 곳", "cuisine_bbq": "고기구이", "spacious": "넓은 곳",
          "cuisine_korean": "한식"}
ALLERGY_TEXT = "새우 알러지가 있어서 못 먹어요"


def _spec_errors(name: str, body) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:pingo-spec#/components/schemas/{name}"}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)]


def line(fact_key=None, wants=None, badge="required", **extra):
    return {"fact_key": fact_key, "wants": wants, "badge": badge, "source": "text"} | extra


def chip(chip_id, label="칩", fact_key=None, wants=None):
    return {"fact_key": fact_key, "wants": wants, "badge": "required", "source": "chip", "chip_id": chip_id,
            "label": label}


def reason(rid, member_key, *lines, text="사유"):
    return {"reaction_id": rid, "member": member_key, "text": text, "lines": list(lines)}


# ---------------------------------------------------------------- must_keep (17번)

def test_required_keyed_line_goes_to_must_keep_with_member_count():
    out = core.summarize_reasons([
        reason("r1", "u1", line("spicy_focused", False)),
        reason("r2", "u2", line("spicy_focused", False)),
    ])
    assert out["must_keep"] == [{"fact_key": "spicy_focused", "wants": False, "member_count": 2,
                                 "reaction_ids": ["r1", "r2"]}]


def test_same_member_same_key_counts_once():
    """한 사람이 같은 키를 두 반응에서 말해도 1명이다. 근거 reaction_id는 둘 다 남는다."""
    out = core.summarize_reasons([
        reason("r1", "u1", line("spicy_focused", False)),
        reason("r2", "u1", line("spicy_focused", False), chip("food_spicy", "매워요", "spicy_focused", False)),
    ])
    [item] = out["must_keep"]
    assert (item["member_count"], item["reaction_ids"]) == (1, ["r1", "r2"])


def test_demoted_cuisine_want_is_not_must_keep():
    """#422: 🚫 글의 "고기 먹고 싶어요"는 tools에서 preferred가 된다 — must_keep에 들어가지 않고 선호로 센다."""
    out = core.summarize_reasons([
        reason("r1", "u1", line("cuisine_korean", False), line("cuisine_bbq", True, "preferred")),
        reason("r2", "u2", line("cuisine_bbq", True, "preferred")),
    ])
    assert [i["fact_key"] for i in out["must_keep"]] == ["cuisine_korean"]
    assert [(i["fact_key"], i["member_count"]) for i in out["common_prefs"]] == [("cuisine_bbq", 2)]


def test_same_key_both_directions_in_must_keep_are_two_items():
    out = core.summarize_reasons([
        reason("r1", "u1", line("spacious", True)),
        reason("r2", "u2", line("spacious", False)),
        reason("r3", "u3", line("spacious", True)),
    ])
    assert [(i["wants"], i["member_count"]) for i in out["must_keep"]] == [(True, 2), (False, 1)]
    assert out["split_prefs"] == []   # 갈림은 선호끼리만 본다


# ---------------------------------------------------------------- common_prefs, split_prefs

def test_common_pref_needs_two_members():
    one = core.summarize_reasons([reason("r1", "u1", line("quiet", True, "preferred"))])
    two = core.summarize_reasons([
        reason("r1", "u1", line("quiet", True, "preferred")),
        reason("r2", "u2", line("quiet", True, "preferred")),
    ])
    assert one["common_prefs"] == []
    assert two["common_prefs"] == [{"fact_key": "quiet", "wants": True, "member_count": 2,
                                    "reaction_ids": ["r1", "r2"]}]


def test_same_member_twice_is_not_a_common_pref():
    out = core.summarize_reasons([
        reason("r1", "u1", line("quiet", True, "preferred")),
        reason("r2", "u1", line("quiet", True, "preferred")),
    ])
    assert out["common_prefs"] == []


def test_want_and_avoid_on_same_key_is_split_not_common():
    out = core.summarize_reasons([
        reason("r1", "u1", line("quiet", True, "preferred")),
        reason("r2", "u2", line("quiet", True, "preferred")),
        reason("r3", "u3", line("quiet", False, "preferred")),
    ])
    assert out["split_prefs"] == [{"fact_key": "quiet", "want_count": 2, "avoid_count": 1,
                                   "want_reaction_ids": ["r1", "r2"], "avoid_reaction_ids": ["r3"]}]
    assert out["common_prefs"] == []


# ---------------------------------------------------------------- 키 없는 사유 세 갈래 (17절 2번)

def test_price_chip_goes_to_not_filtered():
    out = core.summarize_reasons([reason("r1", "u1", chip("food_expensive", "비싸요"), text=None)])
    assert out["not_filtered"] == {"count": 1, "reaction_ids": ["r1"], "notices": ["price"]}
    assert out["vague_fixable"]["count"] == 0


def test_allergy_text_goes_to_not_filtered_and_gets_no_request():
    """알러지 낱말이 든 글의 키 없는 줄은 vague_fixable에 가지 않는다(구체화 요청 없음). 같은 글의 키 있는 줄은 그대로
    칸에 들어간다."""
    out = core.summarize_reasons([
        reason("r1", "u1", line("spicy_focused", False), line(), text="매운 거랑 갑각류 알레르기 있어요"),
        reason("r2", "u2", line(), text=ALLERGY_TEXT),
    ])
    assert out["not_filtered"] == {"count": 2, "reaction_ids": ["r1", "r2"], "notices": ["allergy"]}
    assert out["vague_fixable"] == {"count": 0, "reaction_ids": [], "requests": []}
    assert [i["fact_key"] for i in out["must_keep"]] == ["spicy_focused"]


def test_far_chip_goes_to_vague_fixable_with_distance_request():
    out = core.summarize_reasons([reason("r1", "u1", chip("common_far", "너무 멀어요"), text=None)])
    assert out["vague_fixable"] == {"count": 1, "reaction_ids": ["r1"], "requests": ["far"]}
    assert out["not_filtered"]["count"] == 0


@pytest.mark.parametrize("lines, text", [
    ([line()], "그냥 별로였어요"),                                        # 키 없는 글
    ([chip("common_not_my_taste", "취향이 아니에요")], None),              # 「취향이 아니에요」
    ([line("quiet", None, "preferred")], "조용한지 모르겠어요"),           # 키는 있는데 방향 없음
    ([], "②가 줄을 내지 않은 글"),
])
def test_other_keyless_reasons_go_to_vague_fixable(lines, text):
    out = core.summarize_reasons([reason("r1", "u1", *lines, text=text)])
    assert out["vague_fixable"] == {"count": 1, "reaction_ids": ["r1"], "requests": ["general"]}
    assert out["not_filtered"]["count"] == 0
    assert out["must_keep"] == out["common_prefs"] == out["split_prefs"] == []


def test_retired_allergy_chip_is_not_filtered():
    """뺀 칩 「갑각류 알러지가 있어요」(#425)로 남긴 옛 반응 — 키 없는 칩의 이름에 알러지 낱말이 있다."""
    out = core.summarize_reasons([reason("r1", "u1", chip("food_shellfish", "갑각류 알러지가 있어요"), text=None)])
    assert out["not_filtered"]["notices"] == ["allergy"]
    assert out["vague_fixable"]["count"] == 0


def test_one_reaction_can_be_counted_in_both_keyless_sections():
    out = core.summarize_reasons([
        reason("r1", "u1", chip("cafe_expensive", "비싸요"), chip("common_far", "너무 멀어요"), text=None),
        reason("r2", "u2", line(), text="그냥 그래요"),
    ])
    assert out["not_filtered"] == {"count": 1, "reaction_ids": ["r1"], "notices": ["price"]}
    assert out["vague_fixable"] == {"count": 2, "reaction_ids": ["r1", "r2"], "requests": ["general", "far"]}


def test_stored_summary_has_no_text_or_member():
    out = core.summarize_reasons([
        reason("r1", "u_secret", line(), text=ALLERGY_TEXT),
        reason("r2", "u_secret", line("quiet", True, "preferred"), text="조용해서 좋아요"),
    ])
    dumped = json.dumps(out, ensure_ascii=False)
    assert ALLERGY_TEXT not in dumped and "조용해서" not in dumped and "u_secret" not in dumped
    assert out["reaction_ids"] == ["r1", "r2"]


# ---------------------------------------------------------------- 렌더

def test_render_matches_spec_and_uses_fixed_copy():
    stored = core.summarize_reasons([
        reason("r1", "u1", line("spicy_focused", False), chip("food_expensive", "비싸요")),
        reason("r2", "u2", line("quiet", True, "preferred"), chip("common_far", "너무 멀어요"), text=ALLERGY_TEXT),
        reason("r3", "u3", line("quiet", True, "preferred"), line("cuisine_bbq", True, "preferred")),
        reason("r4", "u1", line("cuisine_bbq", False, "preferred"), line(), text="그냥 그래요"),
    ])
    out = core.render_summary("음식점", stored, NOW, LABELS)
    body = out.model_dump(mode="json")

    assert _spec_errors("AgentSummary", body) == []
    assert [(i.label, i.member_count) for i in out.must_keep] == [("매운맛 전문 제외", 1)]
    assert [(i.label, i.member_count) for i in out.common_prefs] == [("조용한 곳 원함", 2)]
    assert [(s.label, s.want_count, s.avoid_count) for s in out.split_prefs] == [("고기구이", 1, 1)]
    assert out.vague_fixable.requests == [core.SUMMARY_REQUESTS["general"], core.SUMMARY_REQUESTS["far"]]
    assert out.not_filtered.notices == [core.SUMMARY_NOTICES["allergy"], core.SUMMARY_NOTICES["price"]]
    assert (out.vague_fixable.count, out.not_filtered.count) == (2, 2)
    assert ALLERGY_TEXT not in json.dumps(body, ensure_ascii=False)


def test_render_drops_key_without_label():
    stored = core.summarize_reasons([reason("r1", "u1", line("mystery_key", False))])
    assert core.render_summary("음식점", stored, NOW, LABELS).must_keep == []


def test_summary_event_payload_matches_spec():
    summary = core.render_summary("카페", core.summarize_reasons([]), NOW, LABELS)
    event = core.summary_updated_event("map_1", summary)
    assert (event.type, event.channel) == ("agent.summary_updated", "public")
    assert _spec_errors("EvtAgentSummaryUpdated", {"id": 1, "event": event.type, "data": event.payload}) == []


# ---------------------------------------------------------------- 갱신 조건 (8절)

def _reasons(category="음식점", n=1, *, start=0, user="u2", at=NOW - hours(30)):
    """핀 하나에 n개의 사유 있는 반응. 핀은 삭제되지 않았다."""
    p = pin(f"p_{category}", category=category)
    rs = [react(f"r{start + i}", p.pin_id, user, "against", at) for i in range(n)]
    return p, rs, [Reason(reaction_id=r.reaction_id, pin_id=p.pin_id, category=category, alias="m2", type=r.type,
                          text="사유", chips=(), updated_at=r.updated_at, pin_deleted=False) for r in rs]


def _meta(category, ids, at=NOW - hours(10)):
    return core.SummaryMeta(category=category, reaction_ids=frozenset(ids), updated_at=at)


def test_no_summary_and_no_reason_is_not_due():
    assert core.summary_changes(snap(), "음식점", None) is None


def test_first_summary_is_made_from_first_reason():
    p, rs, reasons = _reasons(n=1)
    s = snap(pins=[p], reactions=rs, reasons=reasons)
    assert core.summary_changes(s, "음식점", None) == 1


@pytest.mark.parametrize("new, due", [(2, False), (3, True)])
def test_new_reasons_threshold(new, due):
    """지난 요약 뒤에 새 사유 2개는 그대로, 3개(SUMMARY_NEW_REASONS)면 갱신. 반응한 사람은 지난 요약 전부터 있었다."""
    p, old, old_reasons = _reasons(n=2, at=NOW - hours(30))
    _, fresh, fresh_reasons = _reasons(n=new, start=10, at=NOW - hours(1))
    s = snap(pins=[p], reactions=old + fresh, reasons=old_reasons + fresh_reasons)
    meta = _meta("음식점", [r.reaction_id for r in old])
    assert (core.summary_changes(s, "음식점", meta) is not None) is due


def test_gone_reason_makes_it_due():
    p, rs, reasons = _reasons(n=2)
    s = snap(pins=[p], reactions=rs, reasons=reasons)
    assert core.summary_changes(s, "음식점", _meta("음식점", ["r0", "r1", "r_left"])) == 1


def test_new_member_first_reaction_makes_it_due():
    """u3는 지난 요약 뒤에 이 지도에서 처음 반응했다(사유 없는 ♥). 사유가 늘지 않아도 갱신한다."""
    p, rs, reasons = _reasons(n=1, at=NOW - hours(30))
    first = react("r_new", p.pin_id, "u3", "like", NOW - hours(1))
    s = snap(pins=[p], reactions=rs + [first], reasons=reasons)
    assert core.summary_changes(s, "음식점", _meta("음식점", ["r0"])) == 0


def test_returning_member_reaction_is_not_new():
    """u2는 지난 요약 전에도 반응했다 — 요약 뒤의 반응은 첫 반응이 아니다."""
    p, rs, reasons = _reasons(n=1, at=NOW - hours(30))
    again = react("r_again", p.pin_id, "u2", "like", NOW - hours(1))
    s = snap(pins=[p], reactions=rs + [again], reasons=reasons)
    assert core.summary_changes(s, "음식점", _meta("음식점", ["r0"])) is None


def test_new_member_first_reaction_counts_only_for_its_category():
    food, rs, reasons = _reasons(n=1, at=NOW - hours(30))
    cafe = pin("p_cafe", category="카페")
    first = react("r_new", cafe.pin_id, "u3", "like", NOW - hours(1))
    s = snap(pins=[food, cafe], reactions=rs + [first], reasons=reasons)
    metas = [_meta("음식점", ["r0"]), _meta("카페", [])]
    assert core.summary_changes(s, "음식점", metas[0]) is None
    assert core.summary_changes(s, "카페", metas[1]) == 0


def test_pick_summary_takes_most_changed_category_and_reports_more():
    food, food_rs, food_reasons = _reasons("음식점", n=1)
    cafe, cafe_rs, cafe_reasons = _reasons("카페", n=3, start=10)
    s = snap(pins=[food, cafe], reactions=food_rs + cafe_rs, reasons=food_reasons + cafe_reasons)
    assert core.pick_summary(s, []) == ("카페", True)
    assert core.pick_summary(s, [_meta("카페", ["r10", "r11", "r12"])]) == ("음식점", False)


def test_pick_summary_nothing_due():
    food, rs, reasons = _reasons(n=1)
    s = snap(members=[member("u1"), member("u2"), member("u3")], pins=[food], reactions=rs, reasons=reasons)
    assert core.pick_summary(s, [_meta("음식점", ["r0"])]) == (None, False)


def test_deleted_pin_reason_counts_and_its_author_is_not_new():
    """삭제된 핀의 사유도 센다(8절). 그 반응은 반응 표에 없어도 사유로 첫 반응 시각을 안다."""
    gone = Reason(reaction_id="r_gone", pin_id="p_gone", category="음식점", alias="m2", type="against", text="사유",
                  chips=(Chip("food_spicy", "매워요", "spicy_focused", False),), updated_at=NOW - hours(30),
                  pin_deleted=True)
    s = snap(reasons=[gone])
    assert core.summary_changes(s, "음식점", None) == 1
    assert core.summary_changes(s, "음식점", _meta("음식점", ["r_gone"])) is None

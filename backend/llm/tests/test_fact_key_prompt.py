"""② 사유 구조화의 fact_key 목록 — 스키마(FactKey)·프롬프트·사람 말 대응 (#215).

실제 모델은 부르지 않는다(Luna 응답 확인은 #116). 여기서 보는 건 두 가지다.
1. 프롬프트의 키 목록이 FactKey에서 만들어져 어긋날 수 없다.
2. "회 못 먹어" 같은 사람 말에 대해 모델이 낸 fact_key가 스키마를 통과해 그대로 합쳐진다.
   (예전엔 이 키들이 FactKey에 없어서 검증에서 거부됐다.)
"""

import re
from functools import partial
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from llm import prompts, service
from llm.client import call_planner
from llm.schemas import FACT_KEYS, EvidenceLine, FactKey, PlannedCondition, PlannedReason, PlanningOutput


def _output(*reasons):
    """(text, [(fact_key, wants), ...]) 쌍마다 응답 원소 하나 — index는 위치."""
    return PlanningOutput(reasons=[
        PlannedReason(index=i, text=text, conditions=[PlannedCondition(fact_key=k, wants=w) for k, w in conditions])
        for i, (text, conditions) in enumerate(reasons)
    ])


class TestPromptListIsBuiltFromFactKey:
    def test_every_fact_key_appears_with_its_meaning(self):
        for key in get_args(FactKey):
            assert f"- {key}: {prompts.FACT_KEY_MEANINGS[key]}" in prompts.PLAN_EVIDENCE_PROMPT

    def test_meanings_cover_exactly_the_fact_keys(self):
        assert set(prompts.FACT_KEY_MEANINGS) == set(FACT_KEYS)

    def test_prompt_lists_nothing_beyond_fact_keys(self):
        listed = re.findall(r"^   - ([a-z_]+): ", prompts.PLAN_EVIDENCE_PROMPT, flags=re.MULTILINE)
        assert listed == list(FACT_KEYS)

    def test_retired_capacity_min_is_gone(self):
        assert "capacity_min" not in FACT_KEYS
        assert "capacity_min" not in prompts.PLAN_EVIDENCE_PROMPT
        with pytest.raises(ValidationError):
            EvidenceLine(source="manual", text="4인 이상", badge="required", fact_key="capacity_min")

    def test_missing_meaning_fails_loudly(self):
        with pytest.raises(KeyError, match="cuisine_raw_fish"):
            prompts._render_fact_key_lines(("quiet", "cuisine_raw_fish"), {"quiet": "조용한가"})

    def test_prompt_gives_the_raw_fish_example(self):
        assert '"회 못 먹어" → cuisine_raw_fish' in prompts.PLAN_EVIDENCE_PROMPT

    def test_prompt_tells_gopchang_apart_from_bbq(self):
        # 곱창·막창은 고기구이가 아니라 따로 나눈 키다(#417)
        assert '"삼겹살 먹자"·"갈비 먹고 싶어" → cuisine_bbq' in prompts.PLAN_EVIDENCE_PROMPT
        assert '"곱창 먹자"·"막창 좋아" → cuisine_gopchang' in prompts.PLAN_EVIDENCE_PROMPT


class _FakeClient:
    """모델이 낸 fact_key를 그대로 돌려주는 대역 — 사람 말 → 키 대응을 모델이 맞췄다고 가정한다."""

    def __init__(self, fact_keys):
        output = _output(*[(text, [(key, None)] if key else []) for text, _badge, key in fact_keys])
        message = SimpleNamespace(parsed=output, refusal=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=message)])))


def _reason(text, badge):
    return {"author_id": "u1", "source": "reaction", "text": text, "badge": badge, "fact_key": None}


@pytest.mark.parametrize("text,badge,expected", [
    ("회 못 먹어", "required", "cuisine_raw_fish"),
    ("한식 말고", "preferred", "cuisine_korean"),
    ("고기 먹자", "preferred", "cuisine_bbq"),
    ("곱창 먹자", "preferred", "cuisine_gopchang"),
    ("주차 되는 곳", "preferred", "parking_available"),
    ("강아지랑 갈 수 있는 곳", "preferred", "pet_friendly"),
    ("야경 보고 싶어", "preferred", "night_view"),
    ("아이 데리고 가요", "preferred", "kid_friendly"),
])
def test_human_phrase_maps_to_registry_key(text, badge, expected):
    client = _FakeClient([(text, badge, expected)])

    [[line]] = service._model_planner(client, [_reason(text, badge)])

    assert line.fact_key == expected
    assert line.badge == badge  # 방향(원함/반대)은 badge가 정한다 — 키는 그대로


def test_unrelated_phrase_stays_null():
    client = _FakeClient([("그냥 별로예요", "preferred", None)])

    [[line]] = service._model_planner(client, [_reason("그냥 별로예요", "preferred")])

    assert line.fact_key is None


def test_model_cannot_emit_key_outside_registry():
    with pytest.raises(ValidationError):
        EvidenceLine(source="reaction", text="x", badge="preferred", fact_key="cuisine_pizza")
    with pytest.raises(ValidationError):
        PlannedCondition(fact_key="cuisine_pizza", wants=True)


# ── 방향(wants) — #230 ──────────────────────────────────────────────────────

import json
from pathlib import Path

from llm.prompts import HARD_FACT_KEYS

WANTS_CASES = json.loads((Path(__file__).parent / "fixtures" / "wants_cases.json").read_text(encoding="utf-8"))


class TestWantsSchema:
    def test_wants_without_fact_key_is_normalized_to_none(self):
        line = EvidenceLine(source="reaction", text="x", badge="preferred", wants=True)
        assert (line.fact_key, line.wants) == (None, None)

    def test_model_output_condition_needs_a_key(self):
        # 키 없는 조건은 스키마가 받지 않는다 — "조건 없음"은 빈 conditions로 낸다(#419).
        with pytest.raises(ValidationError):
            PlanningOutput.model_validate(
                {"reasons": [{"index": 0, "text": "x", "conditions": [{"fact_key": None, "wants": True}]}]}
            )

    def test_wants_defaults_to_none(self):
        assert EvidenceLine(source="reaction", text="x", badge="preferred", fact_key="quiet").wants is None

    def test_null_fact_key_with_null_wants_is_fine(self):
        assert EvidenceLine(source="reaction", text="x", badge="preferred").wants is None


class TestWantsMerge:
    def test_model_wants_is_taken_when_input_has_none(self):
        output = _output(("한식 말고", [("cuisine_korean", False)]))

        [[line]] = service.merge_planned([_reason("한식 말고", "required")], output)

        assert (line.fact_key, line.wants) == ("cuisine_korean", False)

    def test_input_wants_is_not_overwritten_by_model(self):
        raw = {**_reason("한식 먹자", "preferred"), "fact_key": "cuisine_korean", "wants": True}

        [[line]] = service.merge_planned([raw], _output(("한식 먹자", [("cuisine_korean", False)])))

        assert line.wants is True

    def test_wants_without_key_is_dropped(self):
        raw = {**_reason("그냥", "preferred"), "wants": False}
        [[line]] = service.merge_planned([raw], _output(("그냥", [])))
        assert (line.fact_key, line.wants) == (None, None)

    def test_unknown_direction_stays_null(self):
        [[line]] = service.merge_planned([_reason("한식", "preferred")], _output(("한식", [("cuisine_korean", None)])))

        assert line.wants is None


class TestWantsPrompt:
    def test_prompt_explains_direction_and_flip_rule(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "wants" in prompt
        assert '"시끄러운 데는 싫어" → quiet, wants=true' in prompt
        assert '"한식 말고" → cuisine_korean, wants=false' in prompt

    def test_prompt_names_every_hard_key_and_asks_for_wants(self):
        section = prompts.PLAN_EVIDENCE_PROMPT.split("안전 키(")[1].split(")")[0]
        for key in HARD_FACT_KEYS:
            assert key in section
        assert "wants는 null로 둔다" not in prompts.PLAN_EVIDENCE_PROMPT
        assert '"저 조개 알러지 있어요" → contains_shellfish, wants=false' in prompts.PLAN_EVIDENCE_PROMPT

    def test_prompt_leans_to_false_for_safety_reasons(self):
        assert "조금이라도 분명하면 false" in prompts.PLAN_EVIDENCE_PROMPT

    def test_hard_keys_are_registered_fact_keys(self):
        assert set(HARD_FACT_KEYS) <= set(FACT_KEYS)

    def test_no_unreplaced_placeholder(self):
        assert "__HARD_KEYS__" not in prompts.PLAN_EVIDENCE_PROMPT
        assert "{fact_key_lines}" not in prompts.PLAN_EVIDENCE_PROMPT


class TestWantsFixtures:
    """#116에서 실제 Luna에 먹일 문장·기대값 쌍이다. 여기서는 파일 자체가 규칙에 맞는지만 본다."""

    def test_at_least_twelve_cases(self):
        assert len(WANTS_CASES) >= 12

    @pytest.mark.parametrize("case", WANTS_CASES, ids=[c["text"] for c in WANTS_CASES])
    def test_case_is_valid_and_consistent(self, case):
        line = EvidenceLine(source="reaction", text=case["text"], badge=case["badge"], fact_key=case["fact_key"], wants=case["wants"])

    def test_at_least_eight_safety_cases_covering_all_directions(self):
        safety = [c for c in WANTS_CASES if c["fact_key"] in HARD_FACT_KEYS]
        assert len(safety) >= 8
        assert {c["wants"] for c in safety} == {True, False, None}

    def test_allergy_and_cannot_eat_cases_expect_false(self):
        for c in WANTS_CASES:
            if c["fact_key"] in HARD_FACT_KEYS and any(w in c["text"] for w in ("알러지", "못 먹", "빼 주세요")):
                assert c["wants"] is False, c["text"]

    def test_cases_cover_both_directions_and_the_flip(self):
        assert {c["wants"] for c in WANTS_CASES} == {True, False, None}
        assert any(c["fact_key"] == "quiet" and c["wants"] is True and "싫" in c["text"] for c in WANTS_CASES)


# ── 줄 text 비교 정규화 — #249 ───────────────────────────────────────────────

import unicodedata


class TestTextEchoNormalization:
    def _merge(self, echoed: str):
        output = _output((echoed, [("cuisine_korean", False)]))
        return service.merge_planned([_reason("한식 말고 다른 거", "required")], output)

    def test_nfd_echo_is_accepted_and_result_keeps_input_text(self):
        [[line]] = self._merge(unicodedata.normalize("NFD", "한식 말고 다른 거"))
        assert line.text == "한식 말고 다른 거" and line.fact_key == "cuisine_korean"

    def test_zero_width_and_spacing_differences_are_accepted(self):
        [[line]] = self._merge("한식\u200b 말고\u00a0 다른\n거")
        assert line.text == "한식 말고 다른 거"

    def test_different_text_is_still_rejected(self):
        with pytest.raises(ValueError):
            self._merge("중식 먹자")


# ── 입력 payload에서 fact_key null 빼기 — #410 ───────────────────────────────

from llm.client import _user_payload


class TestUserPayloadOmitsNullKey:
    """null을 보내면 모델이 "이미 정해진 값"으로 읽고 키를 붙일 사유에도 null을 돌려준다(25%)."""

    def test_line_without_key_has_no_fact_key_field(self):
        [line] = json.loads(_user_payload([_reason("갑각류 알러지 있어요", "required")]))
        assert "fact_key" not in line
        assert line == {"index": 0, "text": "갑각류 알러지 있어요", "badge": "required"}

    def test_missing_fact_key_entry_is_also_omitted(self):
        raw = {"author_id": "u1", "source": "reaction", "text": "한식 말고", "badge": "required"}
        [line] = json.loads(_user_payload([raw]))
        assert "fact_key" not in line

    def test_chip_line_keeps_its_key(self):
        chip = {**_reason("매워요", "required"), "fact_key": "spicy_focused"}
        [line] = json.loads(_user_payload([chip]))
        assert line["fact_key"] == "spicy_focused"

    def test_mixed_batch_keeps_order_and_only_chip_has_key(self):
        chip = {**_reason("매워요", "required"), "fact_key": "spicy_focused"}
        lines = json.loads(_user_payload([chip, _reason("알러지 있어요", "required"), _reason("초밥 먹자", "preferred")]))
        assert [l["index"] for l in lines] == [0, 1, 2]
        assert ["fact_key" in l for l in lines] == [True, False, False]

    def test_payload_contains_no_null_value_at_all(self):
        assert "null" not in _user_payload([_reason("그냥 별로예요", "preferred")])


class TestPromptDescribesOmittedKey:
    def test_input_description_says_key_exists_only_on_chip_lines(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "각 원소는 index·text·badge를 가진다" in prompt
        assert "fact_key는 칩으로 이미 정해진 줄에만 있다" in prompt

    def test_rule_5_only_keeps_a_key_that_is_present(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "입력에 fact_key나 wants가 이미 있으면" not in prompt
        assert "입력 줄에 fact_key가 있으면(칩으로 이미 정해진 줄) 그대로 둔다. 없는 줄은 규칙 3으로 정한다." in prompt

    def test_food_names_map_to_cuisine_keys(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "초밥 먹고 싶어" in prompt and "라멘" in prompt and "돈가스" in prompt
        assert "cuisine_japanese" in prompt.split("음식 이름만 말해도")[1]

    def test_ambiguous_allowance_with_safety_key_is_null(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert '"새우 빼고 시키면 괜찮아요" → contains_shellfish, wants=null' in prompt
        assert '"새우 빼고 주문하면 돼서 상관없어요" → contains_shellfish, wants=null' in prompt


# ── 글 하나에 조건 여럿 — #419 ───────────────────────────────────────────────

MULTI_KEY_CASES = json.loads((Path(__file__).parent / "fixtures" / "multi_key_cases.json").read_text(encoding="utf-8"))


class TestMultiConditionPrompt:
    def test_output_is_one_reason_per_input_with_a_condition_list(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "reasons는 입력과 같은 개수, 같은 순서" in prompt
        assert "index는 입력 index를 그대로" in prompt
        assert "조건이 하나도 없으면 conditions는 빈 목록" in prompt

    def test_prompt_gives_multi_condition_examples(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert '"한식 말고 고기 먹고 싶어요" → cuisine_korean, wants=false / cuisine_bbq, wants=true' in prompt
        assert '"매운 거랑 해산물 둘 다 안 돼요" → spicy_focused, wants=false / contains_shellfish, wants=false' in prompt

    def test_prompt_says_not_to_split_a_single_condition(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "조건이 하나인 글은 나누지 않는다" in prompt
        assert '"회 못 먹어요" → cuisine_raw_fish, wants=false (하나' in prompt
        assert "같은 fact_key를 두 번 넣지 않는다" in prompt

    def test_radius_is_one_per_text(self):
        assert "조건이 여럿이어도 글 하나에 하나다" in prompts.PLAN_EVIDENCE_PROMPT

    def test_prompt_no_longer_asks_to_echo_badge_or_source(self):
        prompt = prompts.PLAN_EVIDENCE_PROMPT
        assert "evidence_lines" not in prompt
        assert "source는 입력 그대로" not in prompt


class TestMultiKeyFixtures:
    """실제 Luna에 먹일 #419 평가셋(test_plan_evidence_live)이 규칙에 맞는지만 본다."""

    @pytest.mark.parametrize("case", MULTI_KEY_CASES, ids=[c["text"] for c in MULTI_KEY_CASES])
    def test_case_is_valid(self, case):
        conditions = [PlannedCondition(fact_key=k, wants=w) for k, w in case["conditions"]]
        assert len({c.fact_key for c in conditions}) == len(conditions)  # 같은 키 두 번 없음

    def test_covers_split_single_and_empty(self):
        sizes = {len(c["conditions"]) for c in MULTI_KEY_CASES}
        assert {0, 1, 2} <= sizes
        assert any(k in HARD_FACT_KEYS for c in MULTI_KEY_CASES if len(c["conditions"]) > 1 for k, _ in c["conditions"])

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
from llm.schemas import FACT_KEYS, EvidenceLine, FactKey, PlanningOutput


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


class _FakeClient:
    """모델이 낸 fact_key를 그대로 돌려주는 대역 — 사람 말 → 키 대응을 모델이 맞췄다고 가정한다."""

    def __init__(self, fact_keys):
        output = PlanningOutput(evidence_lines=[
            EvidenceLine(source="reaction", text=text, badge=badge, fact_key=key)
            for text, badge, key in fact_keys
        ])
        message = SimpleNamespace(parsed=output, refusal=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=message)])))


def _reason(text, badge):
    return {"author_id": "u1", "source": "reaction", "text": text, "badge": badge, "fact_key": None}


@pytest.mark.parametrize("text,badge,expected", [
    ("회 못 먹어", "required", "cuisine_raw_fish"),
    ("한식 말고", "preferred", "cuisine_korean"),
    ("고기 먹자", "preferred", "cuisine_bbq"),
    ("주차 되는 곳", "preferred", "parking_available"),
    ("강아지랑 갈 수 있는 곳", "preferred", "pet_friendly"),
    ("야경 보고 싶어", "preferred", "night_view"),
    ("아이 데리고 가요", "preferred", "kid_friendly"),
])
def test_human_phrase_maps_to_registry_key(text, badge, expected):
    client = _FakeClient([(text, badge, expected)])

    [line] = service._model_planner(client, [_reason(text, badge)])

    assert line.fact_key == expected
    assert line.badge == badge  # 방향(원함/반대)은 badge가 정한다 — 키는 그대로


def test_unrelated_phrase_stays_null():
    client = _FakeClient([("그냥 별로예요", "preferred", None)])

    [line] = service._model_planner(client, [_reason("그냥 별로예요", "preferred")])

    assert line.fact_key is None


def test_model_cannot_emit_key_outside_registry():
    with pytest.raises(ValidationError):
        EvidenceLine(source="reaction", text="x", badge="preferred", fact_key="cuisine_pizza")


# ── 방향(wants) — #230 ──────────────────────────────────────────────────────

import json
from pathlib import Path

from llm.prompts import HARD_FACT_KEYS

WANTS_CASES = json.loads((Path(__file__).parent / "fixtures" / "wants_cases.json").read_text(encoding="utf-8"))


class TestWantsSchema:
    def test_wants_without_fact_key_is_normalized_to_none(self):
        line = EvidenceLine(source="reaction", text="x", badge="preferred", wants=True)
        assert (line.fact_key, line.wants) == (None, None)

    def test_model_output_with_null_key_and_wants_does_not_raise(self):
        out = PlanningOutput.model_validate(
            {"evidence_lines": [{"source": "reaction", "text": "x", "badge": "preferred", "fact_key": None, "wants": True}]}
        )
        assert out.evidence_lines[0].wants is None

    def test_wants_defaults_to_none(self):
        assert EvidenceLine(source="reaction", text="x", badge="preferred", fact_key="quiet").wants is None

    def test_null_fact_key_with_null_wants_is_fine(self):
        assert EvidenceLine(source="reaction", text="x", badge="preferred").wants is None


class TestWantsMerge:
    def test_model_wants_is_taken_when_input_has_none(self):
        planned = EvidenceLine(source="reaction", text="한식 말고", badge="required", fact_key="cuisine_korean", wants=False)

        [line] = service.merge_planned([_reason("한식 말고", "required")], PlanningOutput(evidence_lines=[planned]))

        assert (line.fact_key, line.wants) == ("cuisine_korean", False)

    def test_input_wants_is_not_overwritten_by_model(self):
        raw = {**_reason("한식 먹자", "preferred"), "fact_key": "cuisine_korean", "wants": True}
        planned = EvidenceLine(source="reaction", text="한식 먹자", badge="preferred", fact_key="cuisine_korean", wants=False)

        [line] = service.merge_planned([raw], PlanningOutput(evidence_lines=[planned]))

        assert line.wants is True

    def test_wants_without_key_is_dropped(self):
        raw = {**_reason("그냥", "preferred"), "wants": False}
        [line] = service.merge_planned([raw], PlanningOutput(evidence_lines=[
            EvidenceLine(source="reaction", text="그냥", badge="preferred")]))
        assert (line.fact_key, line.wants) == (None, None)

    def test_unknown_direction_stays_null(self):
        planned = EvidenceLine(source="reaction", text="한식", badge="preferred", fact_key="cuisine_korean")

        [line] = service.merge_planned([_reason("한식", "preferred")], PlanningOutput(evidence_lines=[planned]))

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
        planned = EvidenceLine(source="reaction", text=echoed, badge="required", fact_key="cuisine_korean", wants=False)
        return service.merge_planned([_reason("한식 말고 다른 거", "required")], PlanningOutput(evidence_lines=[planned]))

    def test_nfd_echo_is_accepted_and_result_keeps_input_text(self):
        [line] = self._merge(unicodedata.normalize("NFD", "한식 말고 다른 거"))
        assert line.text == "한식 말고 다른 거" and line.fact_key == "cuisine_korean"

    def test_zero_width_and_spacing_differences_are_accepted(self):
        [line] = self._merge("한식\u200b 말고\u00a0 다른\n거")
        assert line.text == "한식 말고 다른 거"

    def test_different_text_is_still_rejected(self):
        with pytest.raises(ValueError):
            self._merge("중식 먹자")

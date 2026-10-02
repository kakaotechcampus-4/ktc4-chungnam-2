"""② 사유 구조화의 fact_key 목록 — 스키마(FactKey)·프롬프트·사람 말 대응 (#215).

실제 모델은 부르지 않는다(Luna 응답 확인은 #116). 여기서 보는 건 두 가지다.
1. 프롬프트의 키 목록이 FactKey에서 만들어져 어긋날 수 없다.
2. "회 못 먹어" 같은 사람 말에 대해 모델이 낸 fact_key가 스키마를 통과해 그대로 합쳐진다.
   (예전엔 이 키들이 FactKey에 없어서 검증에서 거부됐다.)
"""

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
        listed = [line.split(":")[0].removeprefix("   - ") for line in prompts.PLAN_EVIDENCE_PROMPT.splitlines() if line.startswith("   - ")]
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

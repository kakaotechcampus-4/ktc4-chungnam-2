"""반대 사유 칩 상수(pins/chips.py)가 docs/constraints.md「반대 사유 칩 (v1)」표와 양방향으로 같은지(#312)."""

import re
from pathlib import Path
from typing import get_args

from common import categories
from llm.schemas import FactKey
from pins import chips

CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"
NONE = "(없음)"
WANTS = {"true": True, "false": False, NONE: None}   # 표에 다른 값이 있으면 KeyError로 실패한다

Row = tuple[str, str, str, str | None, bool | None]   # id, label, 카테고리, fact_key, wants


def _key_or_none(cell: str) -> str | None:
    """「(없음)」, 「(없음, #423)」처럼 이유가 붙은 빈칸도 키 없음이다."""
    return None if re.fullmatch(r"\(없음(, [^)]*)?\)", cell) else cell


def _doc_table() -> list[Row]:
    text = CONSTRAINTS.read_text(encoding="utf-8")
    section = text.split("## 반대 사유 칩 (v1)", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"[a-z]+_[a-z_]+", cells[0]):
            chip_id, label, category, fact_key, wants = cells
            rows.append((chip_id, label, category, _key_or_none(fact_key), WANTS[wants]))
    return rows


def _code_table() -> list[Row]:
    return [
        (chip.id, chip.label, category, chip.fact_key, chip.wants)
        for category, items in chips.category_chips().items()
        for chip in items
    ]


def test_code_constants_equal_doc_table_in_both_directions():
    doc, code = _doc_table(), _code_table()
    assert doc, "문서 표를 못 읽었다"
    assert sorted(doc) == sorted(code), (
        f"문서에만: {sorted(set(doc) - set(code))} / 코드에만: {sorted(set(code) - set(doc))}"
    )


def test_chip_ids_are_unique_and_fit_the_spec_limits():
    ids = [chip_id for chip_id, *_ in _code_table()]
    assert len(ids) == len(set(ids))
    assert all(len(chip_id) <= 50 for chip_id in ids)
    assert all(len(label) <= 20 for _, label, *_ in _code_table())


def test_fact_keys_exist_in_llm_fact_key():
    keys = {fact_key for *_, fact_key, _ in _code_table() if fact_key}
    assert keys <= set(get_args(FactKey)), sorted(keys - set(get_args(FactKey)))


def test_chips_for_puts_category_chips_before_common_ones():
    ids = [chip.id for chip in chips.chips_for("카페")]
    assert ids == ["cafe_crowded", "cafe_noisy", "cafe_seat", "cafe_expensive", "common_not_my_taste", "common_far"]


def test_non_reactable_categories_have_no_chips():
    for category in categories.all_categories():
        if not categories.is_reactable(category):
            assert chips.chips_for(category) == []


def test_chip_with_fact_key_has_direction_and_keyless_chip_has_none():
    """키가 있으면 방향도 있다 — 근거 줄의 wants는 fact_key 없이 못 선다(llm.schemas.EvidenceLine)."""
    for chip_id, _, _, fact_key, wants in _code_table():
        assert (fact_key is None) == (wants is None), chip_id


def test_wants_is_not_in_the_api_response_shape():
    """wants는 서버 안에서만 쓴다 — api-spec.yaml ReasonChip에 없다(#412)."""
    assert "wants" not in chips.chips_for("음식점")[0].model_dump()


def test_evidence_chips_fill_key_and_direction_from_the_table_and_keep_legacy_values():
    assert chips.evidence_chips(["food_spicy", "food_cramped", "common_far", "매워요"]) == [
        {"chip_id": "food_spicy", "label": "매워요", "fact_key": "spicy_focused", "wants": False},
        {"chip_id": "food_cramped", "label": "좁아요", "fact_key": "spacious", "wants": True},
        {"chip_id": "common_far", "label": "너무 멀어요", "fact_key": None, "wants": None},
        {"chip_id": "매워요", "label": "매워요", "fact_key": None, "wants": None},   # 옛 값은 깨지지 않고 글로
    ]


def test_shellfish_chip_is_gone_but_old_reactions_keep_its_label():
    """#425 — 새 반응에서는 못 고르고(422), 이미 남긴 반응은 id가 아니라 이름표로 보이며 키는 없다(거르지 않는다)."""
    assert chips.chip_for("food_shellfish") is None
    assert "food_shellfish" in chips.unknown_chip_ids("음식점", ["food_shellfish"])
    assert chips.evidence_chips(["food_shellfish"]) == [
        {"chip_id": "food_shellfish", "label": "갑각류 알러지가 있어요", "fact_key": None, "wants": None},
    ]


def test_price_chips_stay_but_carry_no_key():
    """#423 — 가격 칩은 남기고 키만 뗐다. 근거 줄은 키 없음(「너무 멀어요」와 같다), Pin에도 price_bucket이 없다."""
    from pins.schemas import Pin

    for chip_id in ("food_expensive", "cafe_expensive", "sight_expensive"):
        chip = chips.chip_for(chip_id)
        assert chip is not None and chip.fact_key is None and chip.wants is None, chip_id
    assert "price_bucket" not in Pin.model_fields

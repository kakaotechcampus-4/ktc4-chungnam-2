"""반대 사유 칩 상수(pins/chips.py)가 docs/constraints.md「반대 사유 칩 (v1)」표와 양방향으로 같은지(#312)."""

import re
from pathlib import Path
from typing import get_args

from common import categories
from llm.schemas import FactKey
from pins import chips

CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"
NO_FACT_KEY = "(없음)"


def _doc_table() -> list[tuple[str, str, str, str | None]]:
    text = CONSTRAINTS.read_text(encoding="utf-8")
    section = text.split("## 반대 사유 칩 (v1)", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"[a-z]+_[a-z_]+", cells[0]):
            rows.append((cells[0], cells[1], cells[2], None if cells[3] == NO_FACT_KEY else cells[3]))
    return rows


def _code_table() -> list[tuple[str, str, str, str | None]]:
    return [
        (chip.id, chip.label, category, chip.fact_key)
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
    keys = {fact_key for *_, fact_key in _code_table() if fact_key}
    assert keys <= set(get_args(FactKey)), sorted(keys - set(get_args(FactKey)))


def test_chips_for_puts_category_chips_before_common_ones():
    ids = [chip.id for chip in chips.chips_for("카페")]
    assert ids == ["cafe_crowded", "cafe_noisy", "cafe_seat", "cafe_expensive", "common_not_my_taste", "common_far"]


def test_non_reactable_categories_have_no_chips():
    for category in categories.all_categories():
        if not categories.is_reactable(category):
            assert chips.chips_for(category) == []


def test_reason_text_uses_labels_and_keeps_legacy_values():
    assert chips.reason_text_from_chips(["food_spicy", "common_far"]) == "매워요, 너무 멀어요"
    assert chips.reason_text_from_chips(["too_spicy"]) == "too_spicy"   # 옛 값은 깨지지 않고 그대로

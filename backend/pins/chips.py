"""
반대(🚫) 사유 칩 목록(#60, #312). 정본은 docs/constraints.md「반대 사유 칩 (v1)」표이고, 이 상수는 그 표의
전사다 — 어긋나면 pins/tests/test_chips.py가 실패한다. 칩을 더하거나 바꾸는 것은 루트만 한다(표와 이 목록을 같이).

순수 모듈이다(DB·시간을 건드리지 않는다). 카테고리 칩 다음에 「공통」 칩이 붙는다.
"""

from common import categories
from pins.schemas import ReasonChip

COMMON = "공통"

_CATEGORY_CHIPS: dict[str, tuple[ReasonChip, ...]] = {
    "음식점": (
        ReasonChip(id="food_spicy", label="매워요", fact_key="spicy_focused"),
        ReasonChip(id="food_oily", label="느끼해요", fact_key="oily_focused"),
        ReasonChip(id="food_expensive", label="비싸요", fact_key="price_bucket"),
        ReasonChip(id="food_wait", label="웨이팅이 길어요", fact_key="wait_short"),
        ReasonChip(id="food_cramped", label="좁아요", fact_key="spacious"),
        ReasonChip(id="food_shellfish", label="갑각류 알러지가 있어요", fact_key="contains_shellfish"),
    ),
    "카페": (
        ReasonChip(id="cafe_crowded", label="너무 붐벼요", fact_key="is_crowded_large"),
        ReasonChip(id="cafe_noisy", label="시끄러워요", fact_key="quiet"),
        ReasonChip(id="cafe_seat", label="자리가 불편해요", fact_key="comfortable_seat"),
        ReasonChip(id="cafe_expensive", label="비싸요", fact_key="price_bucket"),
    ),
    "관광지": (
        ReasonChip(id="sight_inaccessible", label="휠체어·유모차로 가기 힘들어요", fact_key="accessible"),
        ReasonChip(id="sight_expensive", label="입장료가 비싸요", fact_key="price_bucket"),
        ReasonChip(id="sight_noisy", label="시끄러워요", fact_key="quiet"),
    ),
    COMMON: (
        ReasonChip(id="common_not_my_taste", label="취향이 아니에요"),
        ReasonChip(id="common_far", label="너무 멀어요"),
    ),
}


def category_chips() -> dict[str, tuple[ReasonChip, ...]]:
    """표의 카테고리 열 → 칩. 「공통」 키를 포함한다(문서 대조 테스트용)."""
    return dict(_CATEGORY_CHIPS)


def chips_for(category: str) -> list[ReasonChip]:
    """그 카테고리의 칩 + 공통 칩. 반응할 수 없는 카테고리(숙소·기타)는 빈 목록."""
    if not categories.is_reactable(category):
        return []
    return [*_CATEGORY_CHIPS.get(category, ()), *_CATEGORY_CHIPS[COMMON]]


def label_for(chip_id: str) -> str | None:
    """칩 id → label. 모르는 id(옛 값)는 None."""
    for chips in _CATEGORY_CHIPS.values():
        for chip in chips:
            if chip.id == chip_id:
                return chip.label
    return None


def reason_text_from_chips(chip_ids: list[str]) -> str:
    """칩 id를 사유 문장으로 — label로 바꿔 ", "로 잇는다(#236). 옛 값(이름 그대로 저장된 것)은 그대로 쓴다."""
    return ", ".join(label_for(chip_id) or chip_id for chip_id in chip_ids)


def unknown_chip_ids(category: str, chip_ids: list[str]) -> list[str]:
    """그 카테고리 목록(공통 포함)에 없는 id."""
    allowed = {chip.id for chip in chips_for(category)}
    return [chip_id for chip_id in chip_ids if chip_id not in allowed]

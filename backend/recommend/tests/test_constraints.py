"""docs/constraints.md 조건별 정의 표 전사(recommend/constraints.py)가 문서와 일치하는지."""

from recommend import constraints


def test_hard_fact_keys_for_restricts_by_category():
    assert constraints.hard_fact_keys_for("음식점") == sorted(
        ["contains_shellfish", "spicy_focused", "oily_focused", "price_bucket"]
    )
    assert constraints.hard_fact_keys_for("카페") == sorted(["contains_shellfish", "price_bucket", "is_crowded_large"])
    assert constraints.hard_fact_keys_for("숙소") == sorted(["contains_shellfish", "price_bucket", "capacity_min"])
    assert constraints.hard_fact_keys_for("관광지") == sorted(["contains_shellfish", "price_bucket", "is_crowded_large"])


def test_safety_fact_keys_have_exclude_unknown_policy():
    """가드레일8 — 안전 조건은 unknown이면 절대 통과시키지 않는다."""
    for key in ("contains_shellfish", "spicy_focused", "oily_focused"):
        assert constraints.HARD_REGISTRY[key].unknown_policy == "exclude"


def test_preference_leaning_fact_keys_have_pass_unknown_policy():
    for key in ("price_bucket", "capacity_min", "is_crowded_large"):
        assert constraints.HARD_REGISTRY[key].unknown_policy == "pass"


def test_soft_fact_keys_are_not_in_hard_registry():
    assert constraints.SOFT_FACT_KEYS.isdisjoint(constraints.HARD_REGISTRY.keys())

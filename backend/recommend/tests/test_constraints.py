"""docs/constraints.md 조건별 정의 표 전사(recommend/constraints.py)가 문서와 일치하는지."""

from recommend import constraints


def test_hard_fact_keys_for_restricts_by_category():
    assert constraints.hard_fact_keys_for("음식점") == sorted(["contains_shellfish", "price_bucket"])
    assert constraints.hard_fact_keys_for("카페") == sorted(["contains_shellfish", "price_bucket", "is_crowded_large"])
    assert constraints.hard_fact_keys_for("관광지") == sorted(["contains_shellfish", "price_bucket", "is_crowded_large"])


def test_safety_fact_keys_have_exclude_unknown_policy():
    """가드레일8 — 안전 조건은 unknown이면 절대 통과시키지 않는다."""
    assert constraints.HARD_REGISTRY["contains_shellfish"].unknown_policy == "exclude"
    assert {k for k, s in constraints.HARD_REGISTRY.items() if s.unknown_policy == "exclude"} == {"contains_shellfish"}


def test_spicy_and_oily_are_soft_taste_keys_not_safety():
    """#378 — 매운맛·기름진 메뉴는 안전이 아니라 취향이다: soft + pass, 음식점에만 적용."""
    for key in ("spicy_focused", "oily_focused"):
        assert key not in constraints.HARD_REGISTRY
        assert constraints.SOFT_REGISTRY[key].unknown_policy == "pass"
        assert constraints.SOFT_REGISTRY[key].categories == frozenset({"음식점"})


def test_preference_leaning_fact_keys_have_pass_unknown_policy():
    for key in ("price_bucket", "is_crowded_large"):
        assert constraints.HARD_REGISTRY[key].unknown_policy == "pass"


def test_accommodation_is_not_a_recommend_category():
    """#145/#146 — 숙소는 추천 대상이 아니다. 레지스트리 어디에도 숙소·capacity_min이 없다."""
    assert "capacity_min" not in constraints.HARD_REGISTRY
    assert all("숙소" not in spec.categories for spec in constraints.HARD_REGISTRY.values())
    assert constraints.hard_fact_keys_for("숙소") == []


def test_every_comparable_fact_key_has_a_reason_label():
    """추천 이유 문장(core.build_reason)에 쓰는 이름 — 레지스트리에 키를 추가하면(#171) 여기도 채워야 한다."""
    comparable = (set(constraints.HARD_REGISTRY) - constraints.VALUE_COMPARISON_UNSUPPORTED) | constraints.SOFT_FACT_KEYS
    assert comparable <= set(constraints.PASSED_LABELS)


def test_every_registry_fact_key_has_a_short_display_name():
    """#231 — 근거 줄의 "한식 제외"에 쓰는 표시 이름. 키를 추가하고 이름을 빠뜨리면 실패한다."""
    registry_keys = set(constraints.HARD_REGISTRY) | constraints.SOFT_FACT_KEYS
    assert registry_keys <= set(constraints.FACT_LABELS)
    assert all(0 < len(name) <= 30 for name in constraints.FACT_LABELS.values())


def test_soft_fact_keys_are_not_in_hard_registry():
    assert constraints.SOFT_FACT_KEYS.isdisjoint(constraints.HARD_REGISTRY.keys())


def test_soft_registry_covers_the_doc_categories_and_is_all_pass():
    """#171 — docs/constraints.md 음식점 15개(+wait_short)·관광지 36개(hard is_crowded_large 포함)와 같은 수."""
    assert all(spec.kind == "soft" and spec.unknown_policy == "pass" for spec in constraints.SOFT_REGISTRY.values())
    assert constraints.SOFT_FACT_KEYS == frozenset(constraints.SOFT_REGISTRY)
    restaurant = set(constraints.soft_fact_keys_for("음식점"))
    assert {"wait_short", "spacious", "long_established", "parking_available", "vegetarian_friendly", "franchise"} <= restaurant
    assert len([k for k in restaurant if k.startswith("cuisine_")]) == 10
    sight = set(constraints.soft_fact_keys_for("관광지"))
    assert len(sight) + len(constraints.hard_fact_keys_for("관광지")) - 2 == 36  # price_bucket·contains_shellfish는 공통 hard
    assert "winter_spot" in sight and "cuisine_korean" not in sight
    assert set(constraints.soft_fact_keys_for("카페")) == {
        "quiet", "comfortable_seat", "local_flavor", "pet_friendly", "accessible",      # 기존 + 관광지 키를 카페에도(#263)
        "bakery", "serves_alcohol", "open_late",                                         # 카페 전용(#263)
        "spacious", "long_established", "vegetarian_friendly", "franchise",             # 음식점 키를 카페에도(#263)
    }
    assert "pet_friendly" in restaurant and "pet_friendly" in sight


def test_heart_signal_table_classifies_every_restaurant_soft_key():
    """#414 — docs/constraints.md "♥에서 선호로 쓰는 라벨 (음식점)" 표 전사. 새 음식점 soft 키는 표에도 넣는다."""
    table = constraints.HEART_SIGNAL_BY_CATEGORY["음식점"]
    assert set(table) == set(constraints.soft_fact_keys_for("음식점"))
    by_use = {use: {k for k, v in table.items() if v == use} for use in ("use", "two_or_more", "unused")}
    assert by_use["use"] == {k for k in table if k.startswith("cuisine_")} and len(by_use["use"]) == 10
    assert by_use["two_or_more"] == {"spicy_focused", "oily_focused", "long_established", "vegetarian_friendly"}
    assert by_use["unused"] == {"franchise", "spacious", "parking_available", "pet_friendly", "wait_short"}
    assert constraints.HEART_SIGNAL_MIN_TRUE_PLACES == 2


def test_heart_signal_defaults_to_use_outside_the_restaurant_table():
    assert constraints.heart_signal_use("카페", "franchise") == "use"
    assert constraints.heart_signal_use("관광지", "quiet") == "use"

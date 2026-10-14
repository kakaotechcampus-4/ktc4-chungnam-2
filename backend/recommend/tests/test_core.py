"""순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md)."""

import pytest

from common.errors import AppError
from common.geo import WALKING_SPEED_M_PER_MIN
from recommend import constraints, core
from recommend.models import RecommendRun
from recommend.ports import Circle
from recommend.schemas import Check


def _run(status: str) -> RecommendRun:
    return RecommendRun(map_id="map_1", category="음식점", requested_by="user_1", status=status)


def test_check_run_ready_passes_when_done():
    core.check_run_ready(_run("done"))  # 예외 없이 통과해야 한다


@pytest.mark.parametrize(
    "status", ["collecting_evidence", "awaiting_region_confirm", "executing", "failed"]
)
def test_check_run_ready_raises_not_ready_when_not_done(status):
    with pytest.raises(AppError) as exc_info:
        core.check_run_ready(_run(status))
    assert exc_info.value.code == "NOT_READY"


# ---------- check_readiness ----------

def test_check_readiness_ready_from_one_opinion_pin():
    assert core.check_readiness(answered_count=1) == {"ready": True, "answered_count": 1, "required_count": 1}
    assert core.check_readiness(answered_count=5) == {"ready": True, "answered_count": 5, "required_count": 1}


def test_check_readiness_not_ready_without_opinion_pin():
    assert core.check_readiness(answered_count=0) == {"ready": False, "answered_count": 0, "required_count": 1}


# ---------- assemble_evidence ----------

def test_assemble_evidence_preserves_reaction_then_manual_order():
    reaction = [{"text": "a"}]
    manual = [{"text": "b"}]
    assert core.assemble_evidence(reaction, manual) == [{"text": "a"}, {"text": "b"}]


# ---------- demote_wanted_place_identity (#422) ----------

def _line(badge, fact_key, wants):
    return {"text": "사유", "badge": badge, "fact_key": fact_key, "wants": wants}


def test_demote_lowers_required_wanted_cuisine_to_preferred():
    (line,) = core.demote_wanted_place_identity([_line("required", "cuisine_bbq", True)], "음식점")
    assert line["badge"] == "preferred"


@pytest.mark.parametrize("line", [
    _line("required", "cuisine_korean", False),   # 피함은 그대로 required
    _line("required", "parking_available", True), # 필요 조건은 그대로
    _line("required", "spacious", True),          # 칩 「좁아요」
    _line("required", "quiet", True),
    _line("required", "cuisine_bbq", None),       # 방향 모름
    _line("required", None, None),
    _line("preferred", "cuisine_bbq", True),
    _line("reference", "cuisine_bbq", True),
])
def test_demote_leaves_every_other_line_alone(line):
    assert core.demote_wanted_place_identity([line], "음식점") == [line]


def test_demote_only_applies_to_restaurant_identity_table():
    line = _line("required", "cuisine_bbq", True)
    assert core.demote_wanted_place_identity([line], "카페") == [line]
    assert core.demote_wanted_place_identity([_line("required", "quiet", True)], "카페") == [_line("required", "quiet", True)]


def test_demote_covers_chip_lines_and_does_not_mutate_input():
    chip_line = {"text": "고기가 먹고 싶어요", "chip_id": "x", "badge": "required", "fact_key": "cuisine_bbq", "wants": True}
    original = dict(chip_line)
    (result,) = core.demote_wanted_place_identity([chip_line], "음식점")
    assert result["badge"] == "preferred" and result["chip_id"] == "x"
    assert chip_line == original


def test_demote_keeps_the_mixed_reason_split_korean_required_bbq_preferred():
    lines = [_line("required", "cuisine_korean", False), _line("required", "cuisine_bbq", True)]
    assert [l["badge"] for l in core.demote_wanted_place_identity(lines, "음식점")] == ["required", "preferred"]


# ---------- circles_all_overlap / region_signature / merge_circles ----------

def test_circles_all_overlap_true_for_zero_or_one_circle():
    assert core.circles_all_overlap([]) is True
    assert core.circles_all_overlap([Circle(35.0, 129.0, 500)]) is True


def test_circles_all_overlap_true_when_within_combined_radius():
    a = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=1000)
    b = Circle(anchor_lat=35.0, anchor_lng=129.001, radius_m=1000)  # 약 90m 떨어짐 — 합보다 훨씬 가깝다
    assert core.circles_all_overlap([a, b]) is True


def test_circles_all_overlap_false_when_far_apart():
    a = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=100)
    b = Circle(anchor_lat=36.0, anchor_lng=130.0, radius_m=100)  # 100km+ 떨어짐
    assert core.circles_all_overlap([a, b]) is False


def test_region_signature_stable_regardless_of_order():
    a = Circle(anchor_lat=35.111111, anchor_lng=129.222222, radius_m=500)
    b = Circle(anchor_lat=35.333333, anchor_lng=129.444444, radius_m=800)
    assert core.region_signature([a, b]) == core.region_signature([b, a])


def test_region_signature_changes_when_circle_changes():
    a = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=500)
    b = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=501)
    assert core.region_signature([a]) != core.region_signature([b])


def test_merge_circles_single_circle_returns_same_circle():
    circle = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=500)
    merged = core.merge_circles([circle])
    assert merged.anchor_lat == pytest.approx(35.0)
    assert merged.anchor_lng == pytest.approx(129.0)
    assert merged.radius_m == 500


def test_merge_circles_empty_raises_value_error():
    with pytest.raises(ValueError):
        core.merge_circles([])


# ---------- widen_radius ----------

def test_next_default_radius_walk_min_steps_five_minutes_up_to_thirty():
    """docs/constraints.md "반경 넓히기 상수" — 15 → 20 → 25 → 30."""
    assert core.next_default_radius_walk_min(15) == 20
    assert core.next_default_radius_walk_min(20) == 25
    assert core.next_default_radius_walk_min(25) == 30


def test_next_default_radius_walk_min_at_limit_raises_widen_limit():
    with pytest.raises(AppError) as exc_info:
        core.next_default_radius_walk_min(30)
    assert exc_info.value.code == "WIDEN_LIMIT"


def test_radius_m_for_walk_min_uses_walking_speed():
    assert core.radius_m_for_walk_min(15) == 15 * WALKING_SPEED_M_PER_MIN


# ---------- is_within_any_region ----------

def test_is_within_any_region_true_when_inside_one_of_several():
    near = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=500)
    far = Circle(anchor_lat=10.0, anchor_lng=10.0, radius_m=500)
    assert core.is_within_any_region(35.0001, 129.0001, [far, near]) is True


def test_is_within_any_region_false_when_outside_all():
    region = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=10)
    assert core.is_within_any_region(36.0, 130.0, [region]) is False


def test_is_within_any_region_false_when_empty():
    assert core.is_within_any_region(35.0, 129.0, []) is False


# ---------- build_check ----------

def test_build_check_unknown_exclude_policy_fails_without_needs_check():
    # 레지스트리에 exclude 키는 없지만(#425) 분기 자체는 정책 값만 보고 정한다.
    check = core.build_check("is_crowded_large", "exclude", known=False, value=None, passes=False)
    assert check.passed is False
    assert check.confidence == "unknown"
    assert check.needs_check is False


def test_build_check_unknown_pass_policy_passes_with_needs_check():
    check = core.build_check("is_crowded_large", "pass", known=False, value=None, passes=False)
    assert check.passed is True
    assert check.confidence == "unknown"
    assert check.needs_check is True


def test_build_check_known_value_uses_given_passes():
    check = core.build_check("is_crowded_large", "pass", known=True, value=True, passes=False)
    assert check.passed is False
    assert check.confidence == "known"
    assert check.needs_check is False


@pytest.mark.parametrize("fact_key, policy, known, value, passes, label", [
    ("is_crowded_large", "pass", True, False, True, "붐비는 대형 장소 아님"),   # 통과한 실격
    ("is_crowded_large", "pass", True, True, False, "붐비는 대형 장소 해당"),   # 탈락한 실격 — 걸린 이유
    ("spicy_focused", "pass", True, True, True, "매운맛 전문점"),            # 취향 키(#378) — 참인 선호
    ("spicy_focused", "pass", False, None, True, "매운맛 전문 확인 필요"),   # 취향 키 모름 → 통과 + 확인 필요
    ("is_crowded_large", "exclude", False, None, False, "붐비는 대형 장소 확인 필요"),  # exclude 모름 → 실격이어도 이름이 보인다
    ("cuisine_korean", "pass", True, True, True, "한식"),                    # 참인 선호
    ("quiet", "pass", True, False, False, "조용한 곳 아님"),                  # 거짓인 선호
    ("quiet", "pass", False, None, True, "조용한 곳 확인 필요"),
    ("is_crowded_large", "pass", False, None, True, "붐비는 대형 장소 확인 필요"),
    ("is_open", "pass", False, None, True, "영업 여부 확인 필요"),
])
def test_build_check_label_is_human_readable(fact_key, policy, known, value, passes, label):
    check = core.build_check(fact_key, policy, known=known, value=value, passes=passes)
    assert check.label == label
    assert check.label not in ("True", "False", "확인 필요", "확인 불가")


@pytest.mark.parametrize("wants, truth, label", [
    (True, True, "조용함"), (True, False, "조용한 곳 아님"),
    (False, False, "조용한 곳 제외"), (False, True, "조용한 곳 제외 안 됨"),
])
def test_to_satisfaction_checks_uses_the_same_label_rule(wants, truth, label):
    check = core.build_check("quiet", "pass", known=True, value=truth, passes=truth)
    (shown,) = core.to_satisfaction_checks([check], {"quiet": wants})
    assert shown.label == label
    assert shown.label == core.condition_label("quiet", satisfied=(truth == wants), wants=wants)


# ---------- apply_disqualifier_filters ----------

def test_apply_disqualifier_filters_fails_candidate_with_any_failing_check():
    passing = core.build_check("a", "exclude", known=True, value=False, passes=True)
    failing = core.build_check("b", "exclude", known=True, value=True, passes=False)
    result = core.apply_disqualifier_filters([[passing], [passing, failing], []])
    assert result == [True, False, True]  # 빈 checks는 all([])==True


def test_apply_disqualifier_filters_ignores_soft_checks_even_when_not_passed():
    """#208 — soft 라벨의 passed는 라벨의 참/거짓값이다. quiet=False(passed=False)여도 실격이 아니다."""
    hard_ok = core.build_check("is_crowded_large", "pass", known=True, value=False, passes=True)
    soft_false = core.build_check("quiet", "pass", known=True, value=False, passes=False)
    hard_fail = core.build_check("is_crowded_large", "pass", known=True, value=True, passes=False)
    result = core.apply_disqualifier_filters([[hard_ok, soft_false], [hard_fail, soft_false], [soft_false]])
    assert result == [True, False, True]


# ---------- funnel_counts ----------

def test_funnel_counts_maps_pairs_to_dicts():
    result = core.funnel_counts([("카테고리 후보 풀", 0), ("반경 밖 제거", 3)])
    assert result == [
        {"label": "카테고리 후보 풀", "removed_count": 0},
        {"label": "반경 밖 제거", "removed_count": 3},
    ]


# ---------- check_retry_limit ----------

@pytest.mark.parametrize("attempt_no", [0, 1, 4])
def test_check_retry_limit_passes_below_limit(attempt_no):
    core.check_retry_limit(attempt_no)  # 예외 없이 통과


@pytest.mark.parametrize("attempt_no", [5, 6])
def test_check_retry_limit_raises_at_or_above_limit(attempt_no):
    with pytest.raises(AppError) as exc_info:
        core.check_retry_limit(attempt_no)
    assert exc_info.value.code == "RETRY_LIMIT"


# ============================================================================
# #112 — build_preference_criteria / score_candidates / build_member_fulfillment /
# select_top_candidates
# ============================================================================


def _check(fact_key: str, *, passed: bool = True, confidence: str = "known") -> Check:
    return Check(fact_key=fact_key, label=str(passed), passed=passed, confidence=confidence, needs_check=False)


def _place(*checks: Check, members: frozenset[str] = frozenset({"u1"})) -> core.HeartedPlace:
    return core.HeartedPlace(checks=list(checks), member_ids=members)


# ---------- build_preference_criteria ----------

def test_build_preference_criteria_takes_majority_value_when_places_disagree():
    # 3곳은 조용하고(quiet=True) 1곳은 시끄러웠다(quiet=False) → "조용함"으로 본다(이슈 본문 예시).
    places = [
        _place(_check("quiet", passed=True)),
        _place(_check("quiet", passed=True)),
        _place(_check("quiet", passed=True)),
        _place(_check("quiet", passed=False)),
    ]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_excludes_fact_key_on_exact_tie():
    places = [_place(_check("quiet", passed=True)), _place(_check("quiet", passed=False))]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=[], preferred_authors={},
    )
    assert "quiet" not in criteria


def test_build_preference_criteria_ignores_unknown_confidence():
    places = [_place(_check("quiet", passed=True, confidence="unknown"))]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {}


def test_build_preference_criteria_excludes_active_disqualifying_fact_keys():
    # 모든 통과 후보가 이미 같은 값이라 점수 차이를 못 만드는 라벨 — 실격 사유로 등록된 것.
    places = [_place(_check("is_crowded_large", passed=False), _check("quiet", passed=True))]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=["is_crowded_large"], preferred_authors={},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_adds_explicit_preference_as_true():
    criteria = core.build_preference_criteria(
        [], disqualifying_fact_keys=[], preferred_authors={"local_flavor": frozenset({"u1"})},
    )
    assert criteria == {"local_flavor": True}


def test_build_preference_criteria_explicit_preference_overrides_tie():
    places = [_place(_check("quiet", passed=True)), _place(_check("quiet", passed=False))]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=[], preferred_authors={"quiet": frozenset({"u1"})},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_uses_only_soft_fact_keys():
    # 하드 체크의 passed는 "실격 아님"이라 라벨 값과 뜻이 다르다 — 소프트 키만 신호로 쓴다.
    places = [_place(_check("is_crowded_large", passed=True), _check("quiet", passed=True))]
    criteria = core.build_preference_criteria(
        places, disqualifying_fact_keys=[],
        preferred_authors={"is_open": frozenset({"u1"})},
    )
    assert criteria == {"quiet": True}


# ---------- score_candidates ----------

def test_score_candidates_counts_preference_author_as_supporter_without_heart():
    # ♥ 이력이 없어도 선호 사유를 쓴 사람은 그 fact_key의 지지자다.
    criteria = {"quiet": True}
    candidates = {"p1": [_check("quiet", passed=True)]}
    authors = {"quiet": frozenset({"u1"})}
    assert core.score_candidates(candidates, [], criteria, authors) == {"p1": 3}


def test_score_candidates_counts_author_who_also_hearted_once():
    # #414 — u1은 ♥도 하고 직접 썼으니 3점(4점이 아니다), u2는 ♥만 해서 1점.
    criteria = {"quiet": True}
    hearted = [_place(_check("quiet", passed=True), members=frozenset({"u1", "u2"}))]
    candidates = {"p1": [_check("quiet", passed=True)]}
    authors = {"quiet": frozenset({"u1"})}
    assert core.score_candidates(candidates, hearted, criteria, authors) == {"p1": 3 + 1}


def test_score_candidates_ignores_non_soft_fact_keys_in_hearted_checks():
    criteria = {"is_crowded_large": True}
    hearted = [_place(_check("is_crowded_large", passed=True))]
    candidates = {"p1": [_check("is_crowded_large", passed=True)]}
    assert core.score_candidates(candidates, hearted, criteria) == {"p1": 0}

def test_score_candidates_scores_only_when_both_sides_are_true():
    criteria = {"quiet": True}
    candidates = {
        "match": [_check("quiet", passed=True)],
        "mismatch": [_check("quiet", passed=False)],
        "unknown": [_check("quiet", passed=True, confidence="unknown")],
    }
    hearted = [_place(_check("quiet", passed=True), members=frozenset({"u1"}))]
    scores = core.score_candidates(candidates, hearted, criteria)
    assert scores == {"match": 1, "mismatch": 0, "unknown": 0}


def test_score_candidates_criteria_false_never_scores():
    # 값이 갈려도 다수결로 False가 확정된 라벨은 "둘 다 참"이 될 수 없어 항상 0점.
    criteria = {"quiet": False}
    candidates = {"p1": [_check("quiet", passed=True)]}
    hearted = [_place(_check("quiet", passed=True))]
    assert core.score_candidates(candidates, hearted, criteria) == {"p1": 0}


def test_score_candidates_adds_member_count_difference():
    criteria = {"quiet": True}
    hearted = [
        _place(_check("quiet", passed=True), members=frozenset({"u1", "u2"})),
        _place(_check("quiet", passed=False), members=frozenset({"u3"})),
    ]
    candidates = {"p1": [_check("quiet", passed=True)]}
    assert core.score_candidates(candidates, hearted, criteria) == {"p1": 2 - 1}


def test_score_candidates_counts_member_once_across_multiple_liked_places():
    # 한 사람이 조용한 카페 3곳에 ♥를 눌러도 1명으로 센다.
    criteria = {"quiet": True}
    hearted = [
        _place(_check("quiet", passed=True), members=frozenset({"u1"})),
        _place(_check("quiet", passed=True), members=frozenset({"u1"})),
        _place(_check("quiet", passed=True), members=frozenset({"u1"})),
    ]
    candidates = {"p1": [_check("quiet", passed=True)]}
    assert core.score_candidates(candidates, hearted, criteria) == {"p1": 1}


def test_score_candidates_sums_across_multiple_matching_fact_keys():
    criteria = {"quiet": True, "local_flavor": True}
    hearted = [_place(_check("quiet", passed=True), _check("local_flavor", passed=True), members=frozenset({"u1"}))]
    candidates = {"p1": [_check("quiet", passed=True), _check("local_flavor", passed=True)]}
    assert core.score_candidates(candidates, hearted, criteria) == {"p1": 2}


def test_unwanted_soft_keys_never_change_the_score():
    """#171 — 음식점 키 15개가 등록돼도, 사람이 원하지 않은 키는 점수에 영향이 없다.
    ♥ 장소는 한식(참)이고 나머지 cuisine_*는 거짓이다. 기준(criteria)에는 한식만 참으로 남고,
    다른 업태가 참인 후보도, cuisine_* 아홉 개가 거짓인 후보도 한식 가산·감점 외에는 0점이다."""
    cuisines = [
        "cuisine_korean", "cuisine_chinese", "cuisine_japanese", "cuisine_western", "cuisine_bunsik",
        "cuisine_chicken_pub", "cuisine_bbq", "cuisine_foreign", "cuisine_raw_fish", "cuisine_buffet",
    ]

    def labels(true_key):
        return [_check(key, passed=(key == true_key)) for key in cuisines]

    hearted = [_place(*labels("cuisine_korean"), _check("spacious", passed=False), members=frozenset({"u1"}))]
    criteria = core.build_preference_criteria(
        hearted, disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria["cuisine_korean"] is True
    assert not any(criteria[key] for key in cuisines if key != "cuisine_korean")

    candidates = {
        "korean": labels("cuisine_korean"),
        "raw_fish": labels("cuisine_raw_fish") + [_check("spacious", passed=True), _check("franchise", passed=True)],
        "chinese": labels("cuisine_chinese"),
    }
    assert core.score_candidates(candidates, hearted, criteria) == {"korean": 1, "raw_fish": 0, "chinese": 0}


def test_soft_keys_nobody_wants_score_zero_for_every_candidate():
    """아무도 ♥하지 않고 선호 사유도 없으면 criteria가 비어 모든 후보가 0점이다(키가 몇 개든)."""
    candidates = {"p1": [_check(key, passed=True) for key in sorted(constraints.SOFT_FACT_KEYS)]}
    criteria = core.build_preference_criteria(
        [], disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {}
    assert core.score_candidates(candidates, [], criteria) == {"p1": 0}


def test_checks_to_show_keeps_hard_and_only_wanted_soft_checks():
    """#216 — hard는 그대로, soft는 원한 키만(known 여부 무관). 원하지 않은 known·unknown soft는 없다."""
    hard_unknown = core.build_check("is_crowded_large", "pass", known=False, value=None, passes=True)
    hard_known = core.build_check("is_open", "pass", known=True, value=True, passes=True)
    unwanted_known = core.build_check("cuisine_chinese", "pass", known=True, value=False, passes=False)
    unwanted_unknown = core.build_check("franchise", "pass", known=False, value=None, passes=False)
    wanted_known = core.build_check("cuisine_korean", "pass", known=True, value=True, passes=True)
    wanted_unknown = core.build_check("wait_short", "pass", known=False, value=None, passes=False)
    checks = [hard_unknown, hard_known, unwanted_known, unwanted_unknown, wanted_known, wanted_unknown]

    shown = core.checks_to_show(checks, {"cuisine_korean", "wait_short"})

    assert [c.fact_key for c in shown] == ["is_crowded_large", "is_open", "cuisine_korean", "wait_short"]
    assert shown[-1].needs_check is True  # 원한 키는 unknown이어도 「확인 필요」로 남는다
    assert shown[2].confidence == "known"  # 원한 키는 known이어도 남는다


# ---------- build_member_fulfillment ----------

def test_build_member_fulfillment_has_spec_shape_with_satisfied_total_by_member():
    criteria = {"quiet": True}
    hearted = [_place(_check("quiet", passed=True), members=frozenset({"u1", "u2"}))]
    result = core.build_member_fulfillment([_check("quiet", passed=True)], hearted, criteria)
    assert result == {
        "satisfied": 2, "total": 2,
        "by_member": [{"user_id": "u1", "satisfied": True}, {"user_id": "u2", "satisfied": True}],
    }


def test_build_member_fulfillment_counts_member_with_unmet_condition_in_total_only():
    criteria = {"quiet": True}
    hearted = [_place(_check("quiet", passed=True), members=frozenset({"u1"}))]
    result = core.build_member_fulfillment([_check("quiet", passed=False)], hearted, criteria)  # 후보가 안 조용함
    assert result == {"satisfied": 0, "total": 1, "by_member": [{"user_id": "u1", "satisfied": False}]}


def test_build_member_fulfillment_requires_all_of_a_members_conditions():
    """한 구성원의 조건이 둘인데 하나만 맞으면 충족으로 세지 않는다."""
    criteria = {"quiet": True, "local_flavor": True}
    hearted = [_place(_check("quiet"), _check("local_flavor"), members=frozenset({"u1"}))]
    candidate = [_check("quiet", passed=True), _check("local_flavor", passed=True, confidence="unknown")]
    result = core.build_member_fulfillment(candidate, hearted, criteria)
    assert result["satisfied"] == 0 and result["total"] == 1


def test_build_member_fulfillment_ignores_members_without_criteria_conditions():
    criteria = {"quiet": True}
    hearted = [
        _place(_check("quiet", passed=True), members=frozenset({"u1"})),
        _place(_check("quiet", passed=False), members=frozenset({"u2"})),  # 반대 값에만 ♥ — 조건 없음
    ]
    result = core.build_member_fulfillment([_check("quiet", passed=True)], hearted, criteria)
    assert [entry["user_id"] for entry in result["by_member"]] == ["u1"]
    assert result["total"] == 1


def test_build_member_fulfillment_empty_when_no_criteria():
    assert core.build_member_fulfillment([_check("quiet")], [], {}) == {"satisfied": 0, "total": 0, "by_member": []}


def test_build_member_fulfillment_includes_preference_author():
    result = core.build_member_fulfillment(
        [_check("quiet", passed=True)], [], {"quiet": True}, {"quiet": frozenset({"u9"})},
    )
    assert result == {"satisfied": 1, "total": 1, "by_member": [{"user_id": "u9", "satisfied": True}]}


def test_preference_author_is_not_offset_by_their_own_opposing_heart():
    """#112 후속 — 같은 fact_key가 False인 곳에 ♥했던 사람이 그 라벨을 선호 사유로 쓰면 지지만
    센다(+1-1 상쇄 금지)."""
    hearted = [_place(_check("quiet", passed=False), members=frozenset({"u1"}))]
    authors = {"quiet": frozenset({"u1"})}
    candidates = {"p1": [_check("quiet", passed=True)]}
    scores = core.score_candidates(candidates, hearted, {"quiet": True}, authors)
    assert scores == {"p1": 3}


def test_opposing_heart_of_another_member_still_offsets_preference_author():
    hearted = [_place(_check("quiet", passed=False), members=frozenset({"u1", "u2"}))]
    authors = {"quiet": frozenset({"u1"})}
    candidates = {"p1": [_check("quiet", passed=True)]}
    # 지지 {u1}(직접 씀 3), 반대 {u2}(♥ 1, u1은 작성자라 빠진다) → 3 - 1
    assert core.score_candidates(candidates, hearted, {"quiet": True}, authors) == {"p1": 3 - 1}


# ---------- build_reason ----------

def test_build_reason_lists_passed_disqualifiers_and_met_preferences_with_member_count():
    checks = [_check("is_crowded_large", passed=True), _check("quiet", passed=True)]
    fulfillment = {"satisfied": 1, "total": 2, "by_member": []}
    reason = core.build_reason(checks, {"quiet": True}, fulfillment)
    assert reason == "실격 조건 통과: 붐비는 대형 장소 아님 · 선호 충족: 조용함 (1/2명)"


def test_build_reason_does_not_claim_unknown_or_failed_checks():
    checks = [
        _check("is_crowded_large", passed=True, confidence="unknown"),
        _check("quiet", passed=False),
        _check("local_flavor", passed=True, confidence="unknown"),
    ]
    reason = core.build_reason(checks, {"quiet": True, "local_flavor": True}, {"satisfied": 0, "total": 1})
    assert "붐비는" not in reason and "조용함" not in reason and "지역색" not in reason


def test_build_reason_falls_back_to_selection_process_when_nothing_to_cite():
    reason = core.build_reason([], {}, {"satisfied": 0, "total": 0})
    assert reason == "반경 안 후보 중 활성 실격 조건에 걸리지 않은 곳이에요"


# ---------- select_top_candidates ----------

def test_select_top_candidates_picks_highest_scores_first():
    candidates = [
        core.ScoredCandidate(place_id="low", score=1, region_label="해운대", lat=35.0, lng=129.0),
        core.ScoredCandidate(place_id="high", score=5, region_label="해운대", lat=35.0, lng=129.0),
        core.ScoredCandidate(place_id="mid", score=3, region_label="해운대", lat=35.0, lng=129.0),
    ]
    anchors = {"해운대": [(35.0, 129.0)]}
    assert core.select_top_candidates(candidates, anchors, limit=3) == ["high", "mid", "low"]


def test_select_top_candidates_region_diversity_never_beats_score():
    # 5점짜리가 전부 해운대고 광안리 최고점이 2점이면 해운대 3곳이 뽑힌다(이슈 본문 예시).
    candidates = [
        core.ScoredCandidate(place_id=f"haeundae_{i}", score=5, region_label="해운대", lat=35.0, lng=129.0)
        for i in range(3)
    ] + [core.ScoredCandidate(place_id="gwangalli", score=2, region_label="광안리", lat=35.1, lng=129.1)]
    anchors = {"해운대": [(35.0, 129.0)], "광안리": [(35.1, 129.1)]}
    result = core.select_top_candidates(candidates, anchors, limit=3)
    assert result == ["haeundae_0", "haeundae_1", "haeundae_2"]


def test_select_top_candidates_tie_break_prefers_unpicked_region():
    candidates = [
        core.ScoredCandidate(place_id="haeundae_a", score=5, region_label="해운대", lat=35.0, lng=129.0),
        core.ScoredCandidate(place_id="haeundae_b", score=5, region_label="해운대", lat=35.0, lng=129.0001),
        core.ScoredCandidate(place_id="gwangalli", score=5, region_label="광안리", lat=35.1, lng=129.1),
    ]
    anchors = {"해운대": [(35.0, 129.0)], "광안리": [(35.1, 129.1)]}
    result = core.select_top_candidates(candidates, anchors, limit=2)
    # 첫 번째는 (동점이라) 거리로 정해지고(해운대_a가 앵커에 더 가까움), 두 번째는 이미 해운대가
    # 뽑혔으니 동점이면 아직 안 뽑힌 광안리를 우선한다 — 해운대_b가 아니라.
    assert result == ["haeundae_a", "gwangalli"]


def test_select_top_candidates_distance_tie_break_uses_average_not_sum():
    # region_a는 기준 핀 1개, region_b는 기준 핀 2개(둘 다 후보와 같은 좌표) — 합으로 비교하면
    # 기준 핀이 적은 region_a가 항상 이겨야 하지만, 평균이므로 둘 다 거리 0으로 동률이다.
    candidates = [
        core.ScoredCandidate(place_id="from_a", score=1, region_label="region_a", lat=35.0, lng=129.0),
        core.ScoredCandidate(place_id="from_b", score=1, region_label="region_b", lat=36.0, lng=130.0),
    ]
    anchors = {"region_a": [(35.0, 129.0)], "region_b": [(36.0, 130.0), (36.0, 130.0)]}
    result = core.select_top_candidates(candidates, anchors, limit=1)
    # 거리가 둘 다 0으로 동률이면 이어지는 min()의 안정 정렬상 먼저 나온 후보(from_a)가 남는다 —
    # 핵심 검증은 "region_b가 핀이 2개라서 불리해지지 않는다"는 것이다(합이었다면 절대 못 이김).
    assert result == ["from_a"]


def test_select_top_candidates_stops_at_limit():
    candidates = [
        core.ScoredCandidate(place_id=f"p{i}", score=i, region_label="r", lat=35.0, lng=129.0) for i in range(5)
    ]
    result = core.select_top_candidates(candidates, {"r": [(35.0, 129.0)]}, limit=3)
    assert len(result) == 3


def test_select_top_candidates_raises_when_no_anchor_points():
    candidates = [core.ScoredCandidate(place_id="p1", score=1, region_label="빈동네", lat=35.0, lng=129.0)]
    with pytest.raises(ValueError):
        core.select_top_candidates(candidates, {}, limit=3)


def test_select_top_candidates_raises_when_anchor_points_empty_list():
    candidates = [core.ScoredCandidate(place_id="p1", score=1, region_label="빈동네", lat=35.0, lng=129.0)]
    with pytest.raises(ValueError):
        core.select_top_candidates(candidates, {"빈동네": []}, limit=3)


# ---------- resolve_label (#190) ----------

def test_resolve_label_returns_known_value_from_place_facts():
    from places.schemas import FactLabel

    assert core.resolve_label([FactLabel("quiet", True, "known")], "quiet") == (True, True)


def test_resolve_label_treats_missing_unknown_and_valueless_known_as_unknown():
    from places.schemas import FactLabel

    labels = [FactLabel("quiet", None, "unknown"), FactLabel("spicy_focused", None, "known")]
    assert core.resolve_label(labels, "quiet") == (False, None)
    assert core.resolve_label(labels, "spicy_focused") == (False, None)   # 값 없는 known을 통과 쪽으로 읽지 않는다
    assert core.resolve_label(labels, "oily_focused") == (False, None)
    assert core.resolve_label([], "quiet") == (False, None)


# ---------- #231 — soft 사유의 방향(wants) ----------

def _label_check(fact_key, *, value=None):
    """soft 라벨 체크 — value가 None이면 모름(known=False)."""
    return core.build_check(fact_key, "pass", known=value is not None, value=value, passes=bool(value))


def test_soft_requirement_wants_false_disqualifies_only_a_true_label():
    flags = core.apply_disqualifier_filters(
        [[_label_check("cuisine_korean", value=True)], [_label_check("cuisine_korean", value=False)],
         [_label_check("cuisine_korean")]],
        [("cuisine_korean", False)],
    )
    assert flags == [False, True, True]


def test_soft_requirement_wants_true_disqualifies_only_a_false_label():
    flags = core.apply_disqualifier_filters(
        [[_label_check("quiet", value=True)], [_label_check("quiet", value=False)], [_label_check("quiet")]],
        [("quiet", True)],
    )
    assert flags == [True, False, True]


def test_soft_checks_without_requirement_never_disqualify():
    assert core.apply_disqualifier_filters([[_label_check("quiet", value=False)]]) == [True]


def test_avoided_authors_subtract_from_a_place_with_the_true_label():
    checks = {"a": [_label_check("cuisine_korean", value=True)], "b": [_label_check("cuisine_korean", value=False)]}
    scores = core.score_candidates(checks, [], {}, {}, {"cuisine_korean": frozenset({"user_1", "user_2"})})
    assert scores == {"a": -3 * 2, "b": 0}  # 피하겠다고 직접 쓴 사람당 −3(#414)


def test_member_fulfillment_counts_disqualifier_authors_as_satisfied():
    """#255 — 실격 사유를 낸 구성원도 total에 센다. 후보가 실격을 통과했으니 충족이고, 선호가 없어도 N명 중 N명이 남는다."""
    result = core.build_member_fulfillment([_check("quiet", passed=True)], [], {}, disqualifier_authors=["u2", "u1"])
    assert result == {"satisfied": 2, "total": 2, "by_member": [
        {"user_id": "u1", "satisfied": True}, {"user_id": "u2", "satisfied": True},
    ]}


def test_member_fulfillment_disqualifier_author_with_unmet_preference_is_not_satisfied():
    """선호 조건도 가진 구성원은 지금처럼 전부 충족해야 충족이다."""
    result = core.build_member_fulfillment(
        [_check("quiet", passed=False)], [], {"quiet": True}, {"quiet": frozenset({"u1"})}, disqualifier_authors=["u1", "u2"],
    )
    assert result["total"] == 2 and result["satisfied"] == 1
    assert {e["user_id"]: e["satisfied"] for e in result["by_member"]} == {"u1": False, "u2": True}


# ---------- #414 — ♥ 신호 거르기(음식점)와 직접 쓴 사유 3점 ----------

def _keys(places):
    return [sorted(c.fact_key for c in place.checks) for place in places]


def test_filter_heart_signals_drops_restaurant_convenience_keys():
    """'쓰지 않음' 키(체인점·넓음·주차·반려동물·웨이팅)는 ♥ 핀에서 참이든 거짓이든 뺀다."""
    unused = ["franchise", "spacious", "parking_available", "pet_friendly", "wait_short"]
    hearted = [_place(_check("cuisine_japanese"), *[_check(k) for k in unused], _check("franchise", passed=False))]
    assert _keys(core.filter_heart_signals(hearted, "음식점")) == [["cuisine_japanese"]]


def test_filter_heart_signals_keeps_cuisine_from_a_single_place():
    hearted = [_place(_check("cuisine_raw_fish"), _check("cuisine_korean", passed=False))]
    assert _keys(core.filter_heart_signals(hearted, "음식점")) == [["cuisine_korean", "cuisine_raw_fish"]]


def test_filter_heart_signals_style_key_needs_two_true_places():
    """'2곳 이상' 키는 참인 ♥ 핀이 1곳이면 참·거짓 모두 빠지고, 2곳이면 참·거짓 모두 남는다(다수결은 그다음)."""
    one = [_place(_check("spicy_focused")), _place(_check("spicy_focused", passed=False))]
    assert _keys(core.filter_heart_signals(one, "음식점")) == [[], []]

    two = [
        _place(_check("spicy_focused")), _place(_check("spicy_focused")), _place(_check("spicy_focused", passed=False)),
    ]
    assert _keys(core.filter_heart_signals(two, "음식점")) == [["spicy_focused"]] * 3


def test_filter_heart_signals_style_key_ignores_unknown_true_labels():
    hearted = [_place(_check("oily_focused")), _place(_check("oily_focused", confidence="unknown"))]
    assert _keys(core.filter_heart_signals(hearted, "음식점")) == [[], []]


def test_filter_heart_signals_counts_places_not_members():
    """한 곳에 두 사람이 ♥해도 1곳이다 — 우연을 거르는 기준은 사람 수가 아니라 가게 수다."""
    hearted = [_place(_check("long_established"), members=frozenset({"u1", "u2"}))]
    assert _keys(core.filter_heart_signals(hearted, "음식점")) == [[]]


def test_filter_heart_signals_leaves_cafe_unchanged():
    """카페·관광지는 아직 나누지 않았다 — 같은 키(franchise·spacious)도 그대로 쓴다."""
    hearted = [_place(_check("franchise"), _check("spacious"), _check("quiet"), members=frozenset({"u1", "u2"}))]
    assert core.filter_heart_signals(hearted, "카페") == hearted


def test_written_preference_for_an_unused_key_still_counts_but_hearts_do_not():
    """'쓰지 않음' 키도 직접 쓰면 그대로 쓴다(3점). ♥만 한 사람은 그 키를 지지한 것으로 세지 않는다."""
    hearted = core.filter_heart_signals([_place(_check("franchise"), members=frozenset({"u2"}))], "음식점")
    authors = {"franchise": frozenset({"u1"})}
    criteria = core.build_preference_criteria(
        hearted, disqualifying_fact_keys=[], preferred_authors=authors,
    )
    assert criteria == {"franchise": True}
    assert core.score_candidates({"p1": [_check("franchise")]}, hearted, criteria, authors) == {"p1": 3}


def test_member_who_hearted_and_wrote_avoid_counts_minus_three_once():
    """♥한 곳이 조용했어도 "조용한 곳은 피하고 싶다"고 직접 쓰면 반대 3점이다(−1−3이 아니다)."""
    hearted = [_place(_check("quiet"), members=frozenset({"u2"}))]
    preferred, avoided = {"quiet": frozenset({"u1"})}, {"quiet": frozenset({"u2"})}
    scores = core.score_candidates({"p1": [_check("quiet")]}, hearted, {"quiet": True}, preferred, avoided)
    assert scores == {"p1": 3 - 3}


def test_written_preference_outweighs_other_heart_labels():
    """2026-10-08 명동 시험 — "초밥 좋아해요"를 직접 썼고 ♥ 핀은 일식+체인점+기름진 메뉴+주차+넓음이었다.
    걸러진 ♥ 신호로는 일식만 남아, 초밥집이 체인 뷔페보다 위다."""
    raw = [_place(
        _check("cuisine_japanese"), _check("franchise"), _check("oily_focused"),
        _check("parking_available"), _check("spacious"), members=frozenset({"u1"}),
    )]
    hearted = core.filter_heart_signals(raw, "음식점")
    authors = {"cuisine_japanese": frozenset({"u1"})}
    criteria = core.build_preference_criteria(
        hearted, disqualifying_fact_keys=[], preferred_authors=authors,
    )
    assert criteria == {"cuisine_japanese": True}

    candidates = {
        "sushi": [_check("cuisine_japanese")],
        "buffet": [_check("cuisine_buffet"), _check("franchise"), _check("oily_focused"),
                   _check("parking_available"), _check("spacious")],
    }
    assert core.score_candidates(candidates, hearted, criteria, authors) == {"sushi": 3, "buffet": 0}

    fulfillment = core.build_member_fulfillment(candidates["buffet"], hearted, criteria, authors)
    assert core.build_reason(candidates["buffet"], criteria, fulfillment) == "반경 안 후보 중 활성 실격 조건에 걸리지 않은 곳이에요"

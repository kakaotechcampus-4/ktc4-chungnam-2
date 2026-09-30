"""순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md)."""

import pytest

from common.errors import AppError
from common.geo import WALKING_SPEED_M_PER_MIN
from recommend import core
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


# ---------- required_count / check_readiness ----------

@pytest.mark.parametrize("member_count,expected", [(0, 0), (1, 1), (2, 1), (3, 2), (4, 2), (5, 3)])
def test_required_count_is_ceil_half(member_count, expected):
    assert core.required_count(member_count) == expected


def test_check_readiness_ready_when_answered_meets_required():
    result = core.check_readiness(answered_count=2, member_count=3)
    assert result == {"ready": True, "answered_count": 2, "required_count": 2}


def test_check_readiness_not_ready_when_answered_below_required():
    result = core.check_readiness(answered_count=1, member_count=4)
    assert result == {"ready": False, "answered_count": 1, "required_count": 2}


# ---------- assemble_evidence ----------

def test_assemble_evidence_preserves_reaction_then_manual_order():
    reaction = [{"text": "a"}]
    manual = [{"text": "b"}]
    assert core.assemble_evidence(reaction, manual) == [{"text": "a"}, {"text": "b"}]


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
    check = core.build_check("contains_shellfish", "exclude", known=False, value=None, passes=False)
    assert check.passed is False
    assert check.confidence == "unknown"
    assert check.needs_check is False


def test_build_check_unknown_pass_policy_passes_with_needs_check():
    check = core.build_check("price_bucket", "pass", known=False, value=None, passes=False)
    assert check.passed is True
    assert check.confidence == "unknown"
    assert check.needs_check is True


def test_build_check_known_value_uses_given_passes():
    check = core.build_check("contains_shellfish", "exclude", known=True, value=True, passes=False)
    assert check.passed is False
    assert check.confidence == "known"
    assert check.needs_check is False


# ---------- apply_disqualifier_filters ----------

def test_apply_disqualifier_filters_fails_candidate_with_any_failing_check():
    passing = core.build_check("a", "exclude", known=True, value=False, passes=True)
    failing = core.build_check("b", "exclude", known=True, value=True, passes=False)
    result = core.apply_disqualifier_filters([[passing], [passing, failing], []])
    assert result == [True, False, True]  # 빈 checks는 all([])==True


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
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_excludes_fact_key_on_exact_tie():
    places = [_place(_check("quiet", passed=True)), _place(_check("quiet", passed=False))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=[], preferred_authors={},
    )
    assert "quiet" not in criteria


def test_build_preference_criteria_ignores_unknown_confidence():
    places = [_place(_check("quiet", passed=True, confidence="unknown"))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {}


def test_build_preference_criteria_excludes_value_comparison_unsupported_fact_keys():
    places = [_place(_check("price_bucket", passed=True))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset({"price_bucket"}), disqualifying_fact_keys=[], preferred_authors={},
    )
    assert criteria == {}


def test_build_preference_criteria_excludes_active_disqualifying_fact_keys():
    # 모든 통과 후보가 이미 같은 값이라 점수 차이를 못 만드는 라벨 — 실격 사유로 등록된 것.
    places = [_place(_check("contains_shellfish", passed=False), _check("quiet", passed=True))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=["contains_shellfish"], preferred_authors={},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_adds_explicit_preference_as_true():
    criteria = core.build_preference_criteria(
        [], excluded_fact_keys=frozenset(), disqualifying_fact_keys=[], preferred_authors={"local_flavor": frozenset({"u1"})},
    )
    assert criteria == {"local_flavor": True}


def test_build_preference_criteria_explicit_preference_overrides_tie():
    places = [_place(_check("quiet", passed=True)), _place(_check("quiet", passed=False))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=[], preferred_authors={"quiet": frozenset({"u1"})},
    )
    assert criteria == {"quiet": True}


def test_build_preference_criteria_uses_only_soft_fact_keys():
    # 하드 체크의 passed는 "실격 아님"이라 라벨 값과 뜻이 다르다 — 소프트 키만 신호로 쓴다.
    places = [_place(_check("contains_shellfish", passed=True), _check("quiet", passed=True))]
    criteria = core.build_preference_criteria(
        places, excluded_fact_keys=frozenset(), disqualifying_fact_keys=[],
        preferred_authors={"is_open": frozenset({"u1"})},
    )
    assert criteria == {"quiet": True}


# ---------- score_candidates ----------

def test_score_candidates_counts_preference_author_as_supporter_without_heart():
    # ♥ 이력이 없어도 선호 사유를 쓴 사람은 그 fact_key의 지지자다.
    criteria = {"quiet": True}
    candidates = {"p1": [_check("quiet", passed=True)]}
    authors = {"quiet": frozenset({"u1"})}
    assert core.score_candidates(candidates, [], criteria, authors) == {"p1": 1}


def test_score_candidates_counts_author_who_also_hearted_once():
    criteria = {"quiet": True}
    hearted = [_place(_check("quiet", passed=True), members=frozenset({"u1", "u2"}))]
    candidates = {"p1": [_check("quiet", passed=True)]}
    authors = {"quiet": frozenset({"u1"})}
    assert core.score_candidates(candidates, hearted, criteria, authors) == {"p1": 2}


def test_score_candidates_ignores_non_soft_fact_keys_in_hearted_checks():
    criteria = {"contains_shellfish": True}
    hearted = [_place(_check("contains_shellfish", passed=True))]
    candidates = {"p1": [_check("contains_shellfish", passed=True)]}
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
    assert scores == {"p1": 1}


def test_opposing_heart_of_another_member_still_offsets_preference_author():
    hearted = [_place(_check("quiet", passed=False), members=frozenset({"u1", "u2"}))]
    authors = {"quiet": frozenset({"u1"})}
    candidates = {"p1": [_check("quiet", passed=True)]}
    # 지지 {u1}, 반대 {u2}(u1은 작성자라 빠진다) → 1 - 1
    assert core.score_candidates(candidates, hearted, {"quiet": True}, authors) == {"p1": 0}


# ---------- build_reason ----------

def test_build_reason_lists_passed_disqualifiers_and_met_preferences_with_member_count():
    checks = [_check("spicy_focused", passed=True), _check("quiet", passed=True)]
    fulfillment = {"satisfied": 1, "total": 2, "by_member": []}
    reason = core.build_reason(checks, {"quiet": True}, fulfillment)
    assert reason == "실격 조건 통과: 매운맛 전문점 아님 · 선호 충족: 조용함 (1/2명)"


def test_build_reason_does_not_claim_unknown_or_failed_checks():
    checks = [
        _check("spicy_focused", passed=True, confidence="unknown"),
        _check("quiet", passed=False),
        _check("local_flavor", passed=True, confidence="unknown"),
    ]
    reason = core.build_reason(checks, {"quiet": True, "local_flavor": True}, {"satisfied": 0, "total": 1})
    assert "매운맛" not in reason and "조용함" not in reason and "지역색" not in reason


def test_build_reason_skips_price_bucket_which_is_never_actually_compared():
    reason = core.build_reason([_check("price_bucket", passed=True)], {}, {"satisfied": 0, "total": 0})
    assert "price_bucket" not in reason and "가격" not in reason


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

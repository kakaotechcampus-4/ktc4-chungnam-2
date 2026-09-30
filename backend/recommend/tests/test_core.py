"""순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md)."""

import pytest

from common.errors import AppError
from recommend import core
from recommend.models import RecommendRun
from recommend.ports import Circle


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

def test_widen_radius_doubles_by_default_factor():
    circle = Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=1000)
    widened = core.widen_radius(circle)
    assert widened.radius_m == round(1000 * core.WIDEN_FACTOR)
    assert widened.anchor_lat == circle.anchor_lat
    assert widened.anchor_lng == circle.anchor_lng


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

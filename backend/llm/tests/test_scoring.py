"""backend/llm/scoring.py 단위 테스트.

DRAFT — 루트 승인 대기 (scoring.py 자체가 임시 취급). 배점 계산·최대 배수 제한이
공식대로 걸리는지만 검증한다.
"""

from llm.scoring import MAX_TAG_MULTIPLIER, TAG_WEIGHTS, compute_score


def test_single_tag_score_is_weight_times_mentions():
    score = compute_score(["quiet"], {"quiet": 2})

    assert score == TAG_WEIGHTS["quiet"] * 2


def test_multiple_tags_sum_independently():
    matched_tags = ["quiet", "wait_short"]
    mention_counts = {"quiet": 1, "wait_short": 3}

    score = compute_score(matched_tags, mention_counts)

    assert score == TAG_WEIGHTS["quiet"] * 1 + TAG_WEIGHTS["wait_short"] * 3


def test_mention_count_is_capped_at_max_tag_multiplier():
    # 같은 태그를 MAX_TAG_MULTIPLIER보다 많이 언급해도 그 이상은 인정하지 않는다.
    score = compute_score(["quiet"], {"quiet": MAX_TAG_MULTIPLIER + 10})

    assert score == TAG_WEIGHTS["quiet"] * MAX_TAG_MULTIPLIER


def test_unweighted_tag_contributes_zero():
    # TAG_WEIGHTS에 없는 태그는 배점을 지어내지 않고 0으로 취급한다.
    score = compute_score(["unknown_tag"], {"unknown_tag": 5})

    assert score == 0


def test_missing_mention_count_contributes_zero():
    # 매칭된 태그라도 mention_counts에 아예 없으면 언급 0명으로 본다.
    score = compute_score(["quiet"], {})

    assert score == 0


def test_empty_matched_tags_returns_zero():
    assert compute_score([], {"quiet": 5}) == 0

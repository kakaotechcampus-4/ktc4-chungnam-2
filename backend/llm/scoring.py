"""backend/llm/scoring.py — ③-b 선호 순위의 고정 배점 공식.

DRAFT — 루트 승인 대기.

팀 결정: ③-b(선호 순위)에서 순위 자체는 모델이 아니라 코드가 고정 공식으로 계산한다.
`/CLAUDE.md` 절대 원칙 7("모델은 통과분의 순위만 매긴다")과 다른 방향이라, 이 파일의
존재·아래 값(TAG_WEIGHTS, MAX_TAG_MULTIPLIER)은 루트가 정식 반영하기 전까지 임시로
취급한다 — docs/architecture.md·backend/llm/CLAUDE.md·backend/recommend/CLAUDE.md에
이 결정이 아직 반영되지 않았다.
"""

from typing import Mapping, Sequence

# DRAFT — 루트 승인 대기. 태그별 배점.
TAG_WEIGHTS: dict[str, int] = {
    "quiet": 3,
    "wait_short": 2,
    "comfortable_seat": 2,
    "local_flavor": 2,
    "taste_good": 2,
}

MAX_TAG_MULTIPLIER = 3  # 같은 태그를 여러 명이 언급해도 3배까지만 인정


def compute_score(matched_tags: Sequence[str], mention_counts: Mapping[str, int]) -> int:
    """DRAFT — 루트 승인 대기.

    matched_tags(이 후보가 실제로 충족한 태그)마다 TAG_WEIGHTS의 배점 × min(그 태그를
    언급한 인원 수, MAX_TAG_MULTIPLIER)를 합산해서 반환한다.

    TAG_WEIGHTS에 없는 태그는 배점 0으로 취급하고(값을 지어내지 않는다), mention_counts에
    없는 태그는 언급 0명으로 취급한다.
    """
    total = 0
    for tag in matched_tags:
        weight = TAG_WEIGHTS.get(tag, 0)
        mentions = min(mention_counts.get(tag, 0), MAX_TAG_MULTIPLIER)
        total += weight * mentions
    return total

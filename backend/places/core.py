"""can_recommend 판정 규칙(순수 함수) — AI 추천 후보 풀에 넣어도 되는 장소인가(2026-10-15 결정).

DB를 모른다. 라벨 수와 정예 여부를 받아 true/false만 정한다. 임계는 아래 상수 한 곳에서 바꾼다(루트가 값을 바꾼다).
새 모델 호출은 없다 — 이미 있는 라벨을 코드가 세는 것이다. 유흥·주점류도 제외하지 않고 같은 규칙을 쓴다.
정본: docs/data-model.md places 절, docs/constraints.md「추천 가능(can_recommend)」.
"""

from __future__ import annotations

# 확정(confidence='known') 라벨 수가 이 값 이상이면 추천 가능. 시작값은 pingo_demo 분포로 정했다(루트가 조정).
KNOWN_LABEL_THRESHOLDS: dict[str, int] = {"음식점": 5, "카페": 3}

# 임계 없이 항상 추천 가능한 분류(관광지는 TourAPI 라벨이 7개 이상으로 모두 충분하다).
ALWAYS_RECOMMENDABLE = frozenset({"관광지"})


def can_recommend(category: str, known_label_count: int, *, curated: bool) -> bool:
    """정예 적재 행은 true. 그 밖에는 분류별 확정 라벨 수가 임계 이상이면 true. 모르는 분류는 false(후보에서 뺀다)."""
    if curated or category in ALWAYS_RECOMMENDABLE:
        return True
    threshold = KNOWN_LABEL_THRESHOLDS.get(category)
    return threshold is not None and known_label_count >= threshold

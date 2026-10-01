"""
docs/constraints.md "조건별 정의" 표를 그대로 옮긴 선언(authz/policy.py가 docs/permissions.md를
전사하는 것과 같은 원칙 — 정본은 docs/constraints.md, **값 변경은 루트만** 한다).

within_radius/is_open은 이 레지스트리에 없다 — constraints.md 자신이 "코드 판정"으로 분류해
라벨(place_facts) 대상에서 뺐다(within_radius는 좌표 계산, is_open은 실시간 조회).
이 둘은 core.py/service.py가 별도로 처리한다.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["hard", "soft"]
UnknownPolicy = Literal["exclude", "pass"]

_ALL_CATEGORIES: frozenset[str] = frozenset({"음식점", "카페", "관광지"})


@dataclass(frozen=True)
class ConstraintSpec:
    fact_key: str
    categories: frozenset[str]  # 이 fact_key가 적용되는 카테고리
    kind: Kind
    unknown_policy: UnknownPolicy


# 실격(hard) 조건 — 5-6 3단계에서 순회 대상.
HARD_REGISTRY: dict[str, ConstraintSpec] = {
    "contains_shellfish": ConstraintSpec("contains_shellfish", _ALL_CATEGORIES, "hard", "exclude"),
    "spicy_focused": ConstraintSpec("spicy_focused", frozenset({"음식점"}), "hard", "exclude"),
    "oily_focused": ConstraintSpec("oily_focused", frozenset({"음식점"}), "hard", "exclude"),
    "price_bucket": ConstraintSpec("price_bucket", _ALL_CATEGORIES, "hard", "pass"),
    "is_crowded_large": ConstraintSpec("is_crowded_large", frozenset({"카페", "관광지"}), "hard", "pass"),
}

# 선호(soft) 조건 — 실격 필터에는 안 쓰이고 순위(llm.rank_candidates)에만 영향(5-1: 선호는
# 애초에 걸러내지 않는다).
SOFT_FACT_KEYS: frozenset[str] = frozenset({"wait_short", "quiet", "comfortable_seat", "local_flavor"})

# 값 기반 비교(가격 상한 등)를 판정하려면 "사용자가 명시한 기준값"이 필요한데,
# docs/data-model.md의 evidence_lines 스키마엔 그 기준값을 담을 컬럼이 없다(badge/fact_key/
# text/circle_*뿐 — 자유 텍스트 text 안에 숫자가 있어도 구조화된 값이 아니다). 이 세션은
# 그래서 price_bucket을 "known이면 표시만 하고 항상 통과시킨다"로 좁혀 구현했다 —
# 실제 상한 비교는 evidence_lines에 값 컬럼이 추가되거나 llm의 구조화 출력에 임계값이 실리는
# 결정이 나야 가능하다(recommend/for_Root.md에 루트 결정 필요 항목으로 보고).
VALUE_COMPARISON_UNSUPPORTED: frozenset[str] = frozenset({"price_bucket"})


# 추천 이유(Candidate.reason) 한 줄에 쓰는 표시 이름 — fact_key를 사용자 문장으로 옮긴다. 값이
# 아니라 "통과/충족했을 때 뭐라고 말하나"이다. 이 표에 없는 키는 이유에서 조용히 빠지므로
# (가드레일 5는 근거가 있는 것만 말하라는 뜻 — 이름 없는 키를 날것으로 노출하지 않는다)
# 레지스트리에 키를 추가할 때(#171) 여기도 같이 채운다. test_constraints.py가 빠진 키를 잡는다.
PASSED_LABELS: dict[str, str] = {
    "contains_shellfish": "갑각류 없음",
    "spicy_focused": "매운맛 전문점 아님",
    "oily_focused": "기름진 메뉴 위주 아님",
    "is_crowded_large": "붐비는 대형 장소 아님",
    "wait_short": "대기가 짧음",
    "quiet": "조용함",
    "comfortable_seat": "좌석이 편함",
    "local_flavor": "지역색이 있음",
}


def hard_fact_keys_for(category: str) -> list[str]:
    return sorted(key for key, spec in HARD_REGISTRY.items() if category in spec.categories)

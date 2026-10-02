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

_RESTAURANT: frozenset[str] = frozenset({"음식점"})
_CAFE: frozenset[str] = frozenset({"카페"})
_RESTAURANT_AND_CAFE: frozenset[str] = frozenset({"음식점", "카페"})
_CAFE_AND_SIGHT: frozenset[str] = frozenset({"카페", "관광지"})
_SIGHT: frozenset[str] = frozenset({"관광지"})

# 선호(soft) 조건 — 실격 필터에는 안 쓰이고 선호 점수(core.score_candidates)에만 쓰인다(5-1: 선호는
# 애초에 걸러내지 않는다). 전부 unknown_policy=pass. 카테고리는 docs/constraints.md 절 그대로다
# (공통 절의 pet_friendly만 전 카테고리).
_SOFT_KEYS_BY_CATEGORY: dict[str, frozenset[str]] = {
    "pet_friendly": _ALL_CATEGORIES,
    # 음식점 (#203)
    **{key: _RESTAURANT for key in (
        "wait_short",
        "cuisine_korean", "cuisine_chinese", "cuisine_japanese", "cuisine_western", "cuisine_bunsik",
        "cuisine_chicken_pub", "cuisine_bbq", "cuisine_foreign", "cuisine_raw_fish", "cuisine_buffet",
        "parking_available",
    )},
    # 음식점·카페 공통 (#203, #263)
    **{key: _RESTAURANT_AND_CAFE for key in ("spacious", "long_established", "vegetarian_friendly", "franchise")},
    # 카페 전용 (#263)
    **{key: _CAFE for key in ("bakery", "serves_alcohol", "open_late")},
    # 카페·관광지 공통
    **{key: _CAFE_AND_SIGHT for key in ("quiet", "comfortable_seat", "local_flavor", "accessible")},   # accessible: 관광지 키를 카페에도(#263)
    # 관광지 (#122) — 성격·공간·자연·활동·동반·계절
    **{key: _SIGHT for key in (
        "restful", "good_view", "photogenic", "night_view", "date_spot", "hallyu_related",
        "traditional_hanok", "modern_architecture", "religious_site",
        "is_indoor", "is_outdoor",
        "mountain", "waterside", "forest", "flower_garden", "seaside",
        "walkable", "hiking", "cycling", "hands_on", "exhibition", "performance", "shopping", "heritage_tour",
        "family_friendly", "kid_friendly",
        "cherry_blossom", "autumn_foliage", "water_play", "winter_spot",
    )},
}
SOFT_REGISTRY: dict[str, ConstraintSpec] = {
    key: ConstraintSpec(key, categories, "soft", "pass") for key, categories in _SOFT_KEYS_BY_CATEGORY.items()
}
SOFT_FACT_KEYS: frozenset[str] = frozenset(SOFT_REGISTRY)

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
    "pet_friendly": "반려동물과 갈 수 있음",
    "cuisine_korean": "한식",
    "cuisine_chinese": "중식",
    "cuisine_japanese": "일식",
    "cuisine_western": "양식",
    "cuisine_bunsik": "분식",
    "cuisine_chicken_pub": "호프·치킨",
    "cuisine_bbq": "고기구이",
    "cuisine_foreign": "외국음식 전문점",
    "cuisine_raw_fish": "횟집",
    "cuisine_buffet": "뷔페",
    "spacious": "단체가 앉기 넓음",
    "long_established": "30년 넘은 노포",
    "parking_available": "주차할 수 있음",
    "vegetarian_friendly": "채식 메뉴가 있음",
    "franchise": "체인점",
    "restful": "쉬어가기 좋음",
    "good_view": "전망이 좋음",
    "photogenic": "사진 찍기 좋음",
    "night_view": "야경이 좋음",
    "date_spot": "데이트하기 좋음",
    "hallyu_related": "한류와 관련이 있음",
    "traditional_hanok": "전통 한옥",
    "modern_architecture": "근현대 건축물",
    "religious_site": "종교 성지",
    "is_indoor": "실내에서 둘러봄",
    "is_outdoor": "야외에서 둘러봄",
    "mountain": "등산로가 있거나 산자락에 있음",
    "waterside": "물가",
    "forest": "숲",
    "flower_garden": "계절 꽃을 볼 수 있음",
    "seaside": "바닷가",
    "walkable": "산책하기 좋음",
    "hiking": "등산하는 곳",
    "cycling": "자전거를 탈 수 있음",
    "hands_on": "직접 해보는 체험이 있음",
    "exhibition": "전시를 볼 수 있음",
    "performance": "공연·축제가 있음",
    "shopping": "쇼핑하기 좋음",
    "heritage_tour": "역사 유적",
    "family_friendly": "가족끼리 가기 좋음",
    "kid_friendly": "아이를 데려가기 좋음",
    "accessible": "휠체어·유모차로 다닐 수 있음",
    "bakery": "빵·디저트가 중심인 카페",
    "serves_alcohol": "술도 파는 카페",
    "open_late": "밤늦게까지 여는 곳",
    "cherry_blossom": "벚꽃 명소",
    "autumn_foliage": "단풍 명소",
    "water_play": "물놀이를 하는 곳",
    "winter_spot": "겨울 명소",
}


# 근거 줄에 그리는 키의 표시 이름(#231) — "한식 제외"·"횟집 선호"처럼 방향 앞에 붙는 짧은 명사구.
# PASSED_LABELS(서술형 "조용함")와 뜻이 달라 별도 표다. 레지스트리의 모든 키가 여기 있어야 하고
# test_constraints.py가 빠진 키(30자 초과 포함)를 잡는다.
FACT_LABELS: dict[str, str] = {
    "contains_shellfish": "갑각류",
    "spicy_focused": "매운맛 전문",
    "oily_focused": "기름진 메뉴 위주",
    "price_bucket": "가격대",
    "is_crowded_large": "붐비는 대형 장소",
    "wait_short": "대기가 짧은 곳",
    "quiet": "조용한 곳",
    "comfortable_seat": "좌석이 편한 곳",
    "local_flavor": "지역색이 있는 곳",
    "pet_friendly": "반려동물 동반",
    "cuisine_korean": "한식",
    "cuisine_chinese": "중식",
    "cuisine_japanese": "일식",
    "cuisine_western": "양식",
    "cuisine_bunsik": "분식",
    "cuisine_chicken_pub": "호프·치킨",
    "cuisine_bbq": "고기구이",
    "cuisine_foreign": "외국음식",
    "cuisine_raw_fish": "횟집",
    "cuisine_buffet": "뷔페",
    "spacious": "넓은 곳",
    "long_established": "노포",
    "parking_available": "주차 가능",
    "vegetarian_friendly": "채식 메뉴",
    "franchise": "체인점",
    "restful": "쉬어가기 좋은 곳",
    "good_view": "전망 좋은 곳",
    "photogenic": "사진 찍기 좋은 곳",
    "night_view": "야경 명소",
    "date_spot": "데이트 코스",
    "hallyu_related": "한류 명소",
    "traditional_hanok": "전통 한옥",
    "modern_architecture": "근현대 건축물",
    "religious_site": "종교 성지",
    "is_indoor": "실내",
    "is_outdoor": "야외",
    "mountain": "등산로·산자락",
    "waterside": "물가",
    "forest": "숲",
    "flower_garden": "꽃 명소",
    "seaside": "바닷가",
    "walkable": "산책하기 좋은 곳",
    "hiking": "등산",
    "cycling": "자전거",
    "hands_on": "체험",
    "exhibition": "전시",
    "performance": "공연·축제",
    "shopping": "쇼핑",
    "heritage_tour": "역사 유적",
    "family_friendly": "가족 나들이",
    "kid_friendly": "아이 동반",
    "accessible": "휠체어·유모차 이용",
    "bakery": "빵·디저트 카페",
    "serves_alcohol": "술도 파는 곳",
    "open_late": "밤늦게까지 여는 곳",
    "cherry_blossom": "벚꽃 명소",
    "autumn_foliage": "단풍 명소",
    "water_play": "물놀이",
    "winter_spot": "겨울 명소",
}


def hard_fact_keys_for(category: str) -> list[str]:
    return sorted(key for key, spec in HARD_REGISTRY.items() if category in spec.categories)


def soft_fact_keys_for(category: str) -> list[str]:
    return sorted(key for key, spec in SOFT_REGISTRY.items() if category in spec.categories)

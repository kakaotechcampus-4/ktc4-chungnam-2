"""
카테고리 정의 한 곳(#280). 카테고리 목록과 카테고리마다 할 수 있는 것을 여기서만 정한다.

목록을 쓰는 곳(스키마 Literal, DB enum, 추천 대상, 자체 DB 분류, 반응 게이팅)은 전부 여기서 꺼낸다.
카테고리를 더하거나 성질을 바꾸면 이 파일만 고친다. DB enum 값이 함께 바뀌면 마이그레이션도 필요하다.
docs/api-spec.yaml(Category, RecommendCategory), DB enum, contracts 목 서버와 어긋나면
common/tests/test_category_drift.py가 실패한다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    name: str
    pinnable: bool       # 핀을 만들 수 있다 = 자체 장소 DB(places)에 이 분류가 있다(#191)
    reactable: bool      # 핀에 반응(♥/△/🚫)을 남길 수 있다(#154)
    recommendable: bool  # AI 대안 추천 대상이다(#145)


# 순서는 스펙 Category enum 순서다. 분류별 집계(GET /maps/{mapId}/counts) 키 순서도 이걸 따른다.
# 숙소와 기타는 v1에서 핀으로 만들 수 없다(자체 DB에 없다). 스키마 호환을 위해 값은 남긴다.
# 기타는 핀이 있으면 일반 핀처럼 반응을 받는다(docs/permissions.md "숙소 핀의 반응 게이팅", #157).
RULES: tuple[CategoryRule, ...] = (
    CategoryRule("음식점", pinnable=True, reactable=True, recommendable=True),
    CategoryRule("카페", pinnable=True, reactable=True, recommendable=True),
    CategoryRule("숙소", pinnable=False, reactable=False, recommendable=False),
    CategoryRule("관광지", pinnable=True, reactable=True, recommendable=True),
    CategoryRule("기타", pinnable=False, reactable=True, recommendable=False),
)

_BY_NAME: dict[str, CategoryRule] = {rule.name: rule for rule in RULES}


def all_categories() -> tuple[str, ...]:
    """스펙 Category, DB enum category(pins.category)."""
    return tuple(rule.name for rule in RULES)


def pinnable() -> tuple[str, ...]:
    """자체 DB가 담는 분류. DB enum place_category(places.category)."""
    return tuple(rule.name for rule in RULES if rule.pinnable)


def recommendable() -> tuple[str, ...]:
    """스펙 RecommendCategory, DB enum recommend_category(recommend_runs·exclusions.category)."""
    return tuple(rule.name for rule in RULES if rule.recommendable)


def is_reactable(category: str) -> bool:
    """없는 카테고리면 KeyError — 스키마와 DB enum이 막으므로 여기 오면 정의가 어긋난 것이다."""
    return _BY_NAME[category].reactable

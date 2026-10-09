"""backend/llm 구조화 출력 스키마.

정본:
- docs/data-model.md `evidence_lines` / `place_facts` 테이블
- docs/constraints.md `fact_key` 레지스트리 (값 변경은 루트만 — 여기서 새 fact_key를 만들지 않는다)
- docs/api-spec.yaml `LabelConfidence`(known/unknown)와 1:1

모델 호출 3곳(backend/llm/CLAUDE.md)에 대응하는 스키마만 담는다:
  ②    PlanningOutput (사유 → 실격/선호/반경 구조화)
  ③-a-1 PlaceFactLabel (장소 라벨링)
  ③-b   RankedCandidate (선호 순위)
"""

from datetime import datetime
from typing import Literal, Optional, Union, get_args

from pydantic import BaseModel, model_validator

# docs/constraints.md `fact_key` 레지스트리와 같다 — backend/integration/test_llm_fact_key_contract.py가
# 양방향으로 강제한다(문서에만 키를 넣으면 CI 실패). 새 키는 루트가 문서에 먼저 넣고, 여기와
# prompts.FACT_KEY_MEANINGS에 같이 넣는다. 값 변경은 루트만이다.
# within_radius / is_open은 표에서도 "코드 판정"으로 분류되어 라벨링(③-a-1)·사유 구조화(②) 대상이
# 아니므로 후보에서 제외한다. 숙소는 AI 추천 대상이 아니라 숙소 전용 키(capacity_min)는 없다(#145).
FactKey = Literal[
    # 공통
    "contains_shellfish",
    "pet_friendly",
    # 음식점
    "spicy_focused",
    "oily_focused",
    "wait_short",
    "cuisine_korean",
    "cuisine_chinese",
    "cuisine_japanese",
    "cuisine_western",
    "cuisine_bunsik",
    "cuisine_chicken_pub",
    "cuisine_bbq",
    "cuisine_gopchang",
    "cuisine_foreign",
    "cuisine_raw_fish",
    "cuisine_buffet",
    "spacious",
    "long_established",
    "parking_available",
    "vegetarian_friendly",
    "franchise",
    # 카페 전용 (#263)
    "bakery",
    "serves_alcohol",
    "open_late",
    # 카페·관광지 공통
    "is_crowded_large",
    "quiet",
    "comfortable_seat",
    "local_flavor",
    # 관광지 — 성격
    "restful",
    "good_view",
    "photogenic",
    "night_view",
    "date_spot",
    "hallyu_related",
    "traditional_hanok",
    "modern_architecture",
    "religious_site",
    # 관광지 — 공간
    "is_indoor",
    "is_outdoor",
    # 관광지 — 자연
    "mountain",
    "waterside",
    "forest",
    "flower_garden",
    "seaside",
    # 관광지 — 활동
    "walkable",
    "hiking",
    "cycling",
    "hands_on",
    "exhibition",
    "performance",
    "shopping",
    "heritage_tour",
    # 관광지 — 동반
    "family_friendly",
    "kid_friendly",
    "accessible",
    # 관광지 — 계절
    "cherry_blossom",
    "autumn_foliage",
    "water_play",
    "winter_spot",
]
FACT_KEYS: tuple[str, ...] = get_args(FactKey)

Badge = Literal["required", "preferred", "reference"]
Confidence = Literal["known", "unknown"]


class EvidenceLine(BaseModel):
    """docs/data-model.md `evidence_lines` 테이블 1:1 반영.

    id/run_id/author_id/created_at은 DB 삽입 시 recommend 모듈이 채우는 값이라
    ②(plan_evidence) 결과 시점엔 비어 있을 수 있어 Optional로 둔다.
    """

    id: Optional[str] = None
    run_id: Optional[str] = None
    author_id: Optional[str] = None
    source: Literal["reaction", "manual"]
    text: str
    chip_id: Optional[str] = None
    badge: Badge
    fact_key: Optional[FactKey] = None
    # 이 특징(fact_key)이 있는 장소를 원하는가 (docs/constraints.md "사유의 방향(wants)과 실격", #228).
    # true="한식 먹자", false="한식 말고". 모르면 None. fact_key가 없으면 반드시 None.
    wants: Optional[bool] = None
    circle_anchor_pin_id: Optional[str] = None
    circle_radius_m: Optional[int] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _wants_needs_fact_key(self) -> "EvidenceLine":
        # 방향은 키가 있을 때만 의미가 있다. 키 없이 wants가 들어와도 예외로 ② 전체를 무너뜨리지 않고 버린다.
        if self.fact_key is None:
            self.wants = None
        return self


class PlannedCondition(BaseModel):
    """② 응답 — 사유 글에서 읽은 조건 하나(키와 방향). 근거 줄 하나가 된다(#419)."""

    fact_key: FactKey
    wants: Optional[bool] = None


class PlannedReason(BaseModel):
    """② 응답 — 입력 글 한 줄에 대한 결과. index·text는 입력과 맞는지 대조하는 데만 쓴다.

    conditions는 0개 이상이다 — 비면 키 없는 줄 하나, 여럿이면 조건마다 줄 하나(#419).
    badge·author 같은 나머지 필드는 받지 않는다 — 모델이 바꿀 수 없는 값이라 에코할 이유가 없다."""

    index: int
    text: str
    conditions: list[PlannedCondition]
    circle_radius_m: Optional[int] = None


class PlanningOutput(BaseModel):
    """② 사유 → 실격/선호/반경 구조화 출력. 입력 글마다 PlannedReason 하나."""

    reasons: list[PlannedReason]


class PlaceFactLabel(BaseModel):
    """③-a-1 장소 라벨링 출력 (docs/api-spec.yaml LabelConfidence와 동일 값셋).

    confidence=unknown일 때 value를 지어내지 않는다 — 반드시 None이어야 한다
    (backend/llm/CLAUDE.md "넘지 말 것", 가드레일 8·9). evidence도 마찬가지다 —
    판정 근거가 없는데 근거 텍스트만 지어내면 안 되므로 unknown이면 evidence도 None이어야 한다.
    unknown_policy 적용·실격 여부 판단은 이 스키마의 책임이 아니다 — recommend가 한다(가드레일 7).
    """

    fact_key: FactKey
    value: Optional[Union[bool, str, int]] = None
    confidence: Confidence
    evidence: Optional[str] = None

    @model_validator(mode="after")
    def _unknown_must_not_have_value(self) -> "PlaceFactLabel":
        if self.confidence == "unknown" and self.value is not None:
            raise ValueError("confidence=unknown인데 value가 채워져 있다 — 값을 지어내면 안 된다")
        if self.confidence == "unknown" and self.evidence is not None:
            raise ValueError("confidence=unknown인데 evidence가 채워져 있다 — 근거를 지어내면 안 된다")
        if self.confidence == "known" and self.value is None:
            raise ValueError("confidence=known이면 value가 있어야 한다")
        return self


class RankedCandidate(BaseModel):
    """③-b 선호 순위 채점 출력. 입력은 이미 실격 통과분이며, 이 스키마는 순위만 매긴다."""

    place_id: str
    rank: int
    member_comment: Optional[str] = None  # 근거 없으면 None (5-7-1) — 지어내지 않는다

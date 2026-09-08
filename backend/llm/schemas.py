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
from typing import Literal, Optional, Union

from pydantic import BaseModel, model_validator

# docs/constraints.md 조건별 정의 표에 명시된 fact_key만 고정한다.
# ("...등"으로 표시된 확장분은 루트가 레지스트리를 늘릴 때 여기도 같이 늘린다.)
# within_radius / is_open은 표에서도 "코드 판정"으로 분류되어 라벨링(③-a-1) 대상이
# 아니므로 place_facts 라벨 스키마의 fact_key 후보에서 제외한다.
FactKey = Literal[
    # 실격(hard) 조건
    "contains_shellfish",
    "spicy_focused",
    "oily_focused",
    "price_bucket",
    "capacity_min",
    "is_crowded_large",
    # 선호(soft) 조건
    "wait_short",
    "quiet",
    "comfortable_seat",
    "local_flavor",
]

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
    circle_anchor_pin_id: Optional[str] = None
    circle_radius_m: Optional[int] = None
    is_active: bool = True
    created_at: Optional[datetime] = None


class PlanningOutput(BaseModel):
    """② 사유 → 실격/선호/반경 구조화 출력."""

    evidence_lines: list[EvidenceLine]


class PlaceFactLabel(BaseModel):
    """③-a-1 장소 라벨링 출력 (docs/api-spec.yaml LabelConfidence와 동일 값셋).

    confidence=unknown일 때 value를 지어내지 않는다 — 반드시 None이어야 한다
    (backend/llm/CLAUDE.md "넘지 말 것", 가드레일 8·9).
    unknown_policy 적용·실격 여부 판단은 이 스키마의 책임이 아니다 — recommend가 한다(가드레일 7).
    """

    fact_key: FactKey
    value: Optional[Union[bool, str, int]] = None
    confidence: Confidence

    @model_validator(mode="after")
    def _unknown_must_not_have_value(self) -> "PlaceFactLabel":
        if self.confidence == "unknown" and self.value is not None:
            raise ValueError("confidence=unknown인데 value가 채워져 있다 — 값을 지어내면 안 된다")
        if self.confidence == "known" and self.value is None:
            raise ValueError("confidence=known이면 value가 있어야 한다")
        return self


class RankedCandidate(BaseModel):
    """③-b 선호 순위 채점 출력. 입력은 이미 실격 통과분이며, 이 스키마는 순위만 매긴다."""

    place_id: str
    rank: int
    member_comment: Optional[str] = None  # 근거 없으면 None (5-7-1) — 지어내지 않는다

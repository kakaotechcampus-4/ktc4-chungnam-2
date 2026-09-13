"""
docs/api-spec.yaml의 pins 태그 스키마와 1:1로 맞춘다.
Pin의 place_name/price_bucket/created_by_display_name/checks/source_run_id는 places/maps/recommend
모듈이 없어 채울 수 없다 — Optional로 두고 라우터에서 response_model_exclude_none으로 생략한다.

Permissions는 여기서 정의하지 않는다 — Pin·EvidenceLine·ShortlistItem이 공유하는 스키마라
authz가 소유한다(#56 이관, mentor-review-plan.md). pins는 authz의 것을 그대로 쓴다.
"""

from typing import Literal

from pydantic import BaseModel, Field

from authz.schemas import Permissions

Category = Literal["음식점", "카페", "숙소", "관광지"]
PinKind = Literal["일반", "AI추천", "확정"]
PriceBucket = Literal["low", "mid", "high"]
LabelConfidence = Literal["known", "unknown"]
ReactionKind = Literal["like", "neutral", "against"]
PinSource = Literal["link", "search", "coordinate"]


class Check(BaseModel):
    fact_key: str
    label: str
    passed: bool
    confidence: LabelConfidence
    needs_check: bool


class ReactionSummary(BaseModel):
    like: int = 0
    neutral: int = 0
    against: int = 0


class PinCreateRequest(BaseModel):
    category: Category
    source: PinSource | None = None
    link_url: str | None = None
    place_id: str | None = None
    lat: float | None = None
    lng: float | None = None


class Pin(BaseModel):
    id: str
    map_id: str
    category: Category
    kind: PinKind
    visibility: Literal["public", "private"]
    lat: float
    lng: float
    place_name: str | None = None
    created_by: str
    created_by_display_name: str | None = None
    price_bucket: PriceBucket | None = None
    checks: list[Check] | None = None
    source_run_id: str | None = None
    reaction_summary: ReactionSummary = Field(default_factory=ReactionSummary)
    permissions: Permissions


class ReactionRequest(BaseModel):
    type: ReactionKind
    reason_text: str | None = Field(default=None, max_length=140)
    reason_chip_ids: list[str] | None = None


class Reaction(BaseModel):
    pin_id: str
    user_id: str
    type: ReactionKind
    reason_text: str | None = None


class Error(BaseModel):
    code: str
    message: str
    detail: dict | None = None

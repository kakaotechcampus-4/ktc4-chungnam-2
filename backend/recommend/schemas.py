"""
docs/api-spec.yaml의 recommend 태그 스키마와 1:1. Permissions는 authz.schemas가 소유(pins·
shortlist와 같은 재사용 원칙) — 이 모듈은 candidate 전용 permissions(can_publish, #64)를
채울 때도 authz.core.can()을 그대로 부른다(recommend/service.py 참고).
"""

from typing import Literal

from pydantic import BaseModel, Field

from authz.schemas import Permissions

Category = Literal["음식점", "카페", "숙소", "관광지"]
RunStatus = Literal["collecting_evidence", "awaiting_region_confirm", "executing", "done", "failed"]
Badge = Literal["required", "preferred", "reference"]
LabelConfidence = Literal["known", "unknown"]


class Check(BaseModel):
    fact_key: str
    label: str
    passed: bool
    confidence: LabelConfidence
    needs_check: bool


class Readiness(BaseModel):
    ready: bool
    answered_count: int
    required_count: int


class RunCreateRequest(BaseModel):
    category: Category


class RecommendRun(BaseModel):
    id: str
    map_id: str
    category: Category
    status: RunStatus
    attempt_no: int


class EvidenceLine(BaseModel):
    id: str
    author_id: str
    author_display_name: str | None = None  # auth 없어 못 채움(pins/for_Root.md와 같은 갭)
    text: str = Field(max_length=140)
    badge: Badge
    fact_key: str | None = None
    is_active: bool
    permissions: Permissions


class EvidenceToggleEntry(BaseModel):
    id: str
    is_active: bool


class EvidenceAddEntry(BaseModel):
    text: str = Field(max_length=140)


class EvidencePatchRequest(BaseModel):
    toggle: list[EvidenceToggleEntry] = Field(default_factory=list)
    add: list[EvidenceAddEntry] = Field(default_factory=list)


class Region(BaseModel):
    id: str
    label: str
    signature: str
    confirmed: bool


class RegionConfirmRequest(BaseModel):
    accept_union: bool = False


class Candidate(BaseModel):
    id: str
    place_name: str | None = None  # places 없어 못 채움
    region_label: str | None = None
    rank: int
    checks: list[Check]
    visibility: Literal["private", "published"]
    published_pin_id: str | None = None
    permissions: Permissions


class FunnelEntry(BaseModel):
    label: str
    removed_count: int


class RecommendResult(BaseModel):
    run_id: str
    funnel: list[FunnelEntry]
    regions: list[Region]
    candidates: list[Candidate]

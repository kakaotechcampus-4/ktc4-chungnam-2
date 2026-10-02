"""
docs/api-spec.yaml의 recommend 태그 스키마와 1:1. Permissions는 authz.schemas가 소유(pins·
shortlist와 같은 재사용 원칙) — 이 모듈은 candidate 전용 permissions(can_publish, #64)를
채울 때도 authz.core.can()을 그대로 부른다(recommend/service.py 참고).
"""

from typing import Literal

from pydantic import BaseModel, Field

from authz.schemas import Permissions

Category = Literal["음식점", "카페", "관광지"]  # 스펙의 RecommendCategory — 숙소는 추천 대상이 아니다(#145)
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
    default_radius_walk_min: int  # 기본값 원의 현재 도보 시간(분) — 반경 넓히기마다 +5, 상한 30


class EvidenceLine(BaseModel):
    id: str
    author_id: str
    author_display_name: str | None = None  # auth 없어 못 채움(pins/for_Root.md와 같은 갭)
    text: str = Field(max_length=140)
    badge: Badge
    fact_key: str | None = None
    fact_label: str | None = None  # fact_key의 표시 이름("한식") — constraints.FACT_LABELS
    wants: bool | None = None  # 이 특징이 있는 장소를 원하는가(#228). None = 모름
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


class MemberFulfillmentEntry(BaseModel):
    user_id: str
    display_name: str | None = None  # auth 없어 못 채움(EvidenceLine.author_display_name과 같은 갭)
    satisfied: bool


class MemberFulfillment(BaseModel):
    satisfied: int = Field(ge=0)
    total: int = Field(ge=0)
    by_member: list[MemberFulfillmentEntry] | None = None


class PlaceSource(BaseModel):
    provider: Literal["kakao", "naver", "google"]
    url: str | None = None


class Candidate(BaseModel):
    id: str
    place_name: str | None = None  # places 없어 못 채움
    region_label: str | None = None
    rank: int
    checks: list[Check]
    reason: str | None = None
    member_fulfillment: MemberFulfillment | None = None
    place_source: PlaceSource | None = None
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

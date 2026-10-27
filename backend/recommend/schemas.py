"""
docs/api-spec.yaml의 recommend 태그 스키마와 1:1. Permissions는 authz.schemas가 소유(pins·
shortlist와 같은 재사용 원칙) — 이 모듈은 candidate 전용 permissions(can_publish, #64)를
채울 때도 authz.core.can()을 그대로 부른다(recommend/service.py 참고).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from authz.schemas import Permissions
from common import categories

Category = Literal[categories.recommendable()]  # 스펙의 RecommendCategory(common/categories.py, #280)
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
    attempt_limit: int  # 한 사람이 한 지도에서 받을 수 있는 횟수 상한(core.ATTEMPT_LIMIT)
    default_radius_walk_min: int  # 기본값 원의 현재 도보 시간(분) — 반경 넓히기마다 +5, 상한 30


class RunSummary(BaseModel):
    """GET /maps/{mapId}/runs 한 건(#469) — 내가 요청한 run만 온다."""
    id: str
    map_id: str
    category: Category
    status: RunStatus
    attempt_no: int
    attempt_limit: int  # RecommendRun.attempt_limit과 같다
    created_at: datetime
    candidate_count: int = Field(ge=0)  # 마지막 시도의 후보 수. done이 아니면 0
    published_count: int = Field(ge=0)  # 그 run에서 게시한 후보 수


class EvidenceLine(BaseModel):
    id: str
    author_id: str
    author_display_name: str | None = None  # 아직 채우지 않음(#762)
    text: str = Field(max_length=140)
    badge: Badge
    fact_key: str | None = None
    fact_label: str | None = None  # fact_key의 표시 이름("한식") — constraints.FACT_LABELS
    wants: bool | None = None  # 이 특징이 있는 장소를 원하는가(#228). None = 모름
    # 후보를 거르거나 점수 매기는 데 실제로 쓰이는 줄인가(#720, #740) — core.evidence_line_use가 파이프라인과 같은 기준으로 정한다.
    # 끈 줄(is_active=false)도 켜면 쓰이는지를 보인다. 쓰이지 않으면 이유(not_enforced_reason)가 따라온다. 응답에는 항상 채워 내려 준다.
    enforced: bool | None = None
    not_enforced_reason: Literal["no_key", "no_direction", "not_for_category", "off_season"] | None = None
    is_active: bool
    permissions: Permissions


class EvidenceToggleEntry(BaseModel):
    id: str
    is_active: bool


EVIDENCE_ADD_PER_REQUEST = 5   # 「+」 한 번에 글 5개까지(docs/api-spec.yaml add.maxItems, #707). run 하나 상한은 core.MANUAL_EVIDENCE_LIMIT


class EvidenceAddEntry(BaseModel):
    # 앞뒤 공백을 뗀 뒤 1~140자 — 빈 값·공백만은 422(#707, #716)
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]


class EvidencePatchRequest(BaseModel):
    toggle: list[EvidenceToggleEntry] = Field(default_factory=list)
    # 한 요청 5개(api-spec maxItems, 넘으면 422 VALIDATION_ERROR, #707). run 하나 상한은 core.MANUAL_EVIDENCE_LIMIT(글 수).
    add: list[EvidenceAddEntry] = Field(default_factory=list, max_length=EVIDENCE_ADD_PER_REQUEST)


class Region(BaseModel):
    id: str
    label: str
    signature: str
    confirmed: bool


class RegionConfirmRequest(BaseModel):
    accept_union: bool = False


class MemberFulfillmentEntry(BaseModel):
    user_id: str
    display_name: str | None = None  # 아직 채우지 않음, FE가 구성원 목록으로 대신한다(#762)
    satisfied: bool


class MemberFulfillment(BaseModel):
    satisfied: int = Field(ge=0)
    total: int = Field(ge=0)
    by_member: list[MemberFulfillmentEntry] | None = None


class PlaceSource(BaseModel):
    provider: Literal["kakao", "naver", "google", "permit", "tourapi"]
    url: str | None = None


class Candidate(BaseModel):
    id: str
    place_name: str | None = None  # places 없어 못 채움
    region_label: str | None = None
    # 자체 DB 장소의 좌표(candidates.lat/lng, #391) — 「지도에 올리기」 전에도 지도에 그릴 수 있게.
    lat: float | None = None
    lng: float | None = None
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

"""
docs/api-spec.yaml의 recommend 태그 스키마와 1:1. Permissions는 authz.schemas가 소유(pins·
shortlist와 같은 재사용 원칙) — 이 모듈은 candidate 전용 permissions(can_publish, #64)를
채울 때도 authz.core.can()을 그대로 부른다(recommend/service.py 참고).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt, StringConstraints

from authz.schemas import Permissions
from common import categories
from places.schemas import ExternalSearch   # 카카오맵 검색 링크 응답 — 정의는 places(#903), 추천 응답도 같은 타입

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
    # 기본 지역에서 넓히기 상한 안의 정예 장소 수(#798). 의견 핀이 없어 기본 지역이 없으면 둘 다 없다
    curated_nearby: int | None = Field(default=None, ge=0)
    external_search: ExternalSearch | None = None  # curated_nearby가 0일 때만
    radius_m: int | None = None   # 기본 추천 반경(m) — 화면이 run을 만들기 전에 원을 그린다. 모든 카테고리 같다(core.DEFAULT_RADIUS_M, #1385)
    radius_min_m: int | None = None   # 사용자가 고를 수 있는 반경의 하한(core.MIN_RADIUS_M, #1416)
    radius_max_m: int | None = None   # 상한(core.WIDEN_LIMIT_M)


class RunCenter(BaseModel):
    lat: float = Field(ge=33, le=39)
    lng: float = Field(ge=124, le=132)


class RunCreateRequest(BaseModel):
    category: Category
    center: RunCenter | None = None
    # 추천 반경(m, #1416). 정수만(소수·문자열·불리언은 422), 2000~5000(core.MIN_RADIUS_M·WIDEN_LIMIT_M와 같은 값 — 순환 import라 적는다). 없으면 3000
    # 생략은 None이지만 명시한 null은 422다(계약) — 타입은 정수이고 기본값 None은 검증하지 않는다.
    radius_m: StrictInt = Field(None, ge=2000, le=5000)
    execute: bool = False   # true면 근거 조립 뒤 곧바로 첫 검색까지 한 요청에서 끝낸다(#845, #847). 생략은 false


class RecommendRun(BaseModel):
    id: str
    map_id: str
    category: Category
    status: RunStatus
    attempt_no: int
    default_radius_walk_min: int  # 호환용(곧 없앤다) — round(default_radius_m / 80)
    default_radius_m: int | None = None   # 기본값 원의 현재 반경(m) — 기본 3000, 넓히기마다 +1000, 상한 5000(core, #1385)
    next_default_radius_m: int | None = None   # 넓히면 바뀔 반경(m). 이미 상한이면 null(#1370)


class RunSummary(BaseModel):
    """GET /maps/{mapId}/runs 한 건(#469) — 내가 요청한 run만 온다."""
    id: str
    map_id: str
    category: Category
    status: RunStatus
    attempt_no: int
    created_at: datetime
    candidate_count: int = Field(ge=0)  # 마지막 시도의 후보 수. done이 아니면 0
    published_count: int = Field(ge=0)  # 그 run에서 게시한 후보 수
    default_radius_m: int | None = None   # RecommendRun.default_radius_m과 같은 값(#1164)
    next_default_radius_m: int | None = None   # 넓히면 바뀔 반경(m), 이미 상한이면 null(#1370)


class EvidenceLine(BaseModel):
    id: str
    author_id: str
    author_display_name: str | None = None
    text: str = Field(max_length=140)
    badge: Badge
    fact_key: str | None = None
    fact_label: str | None = None  # fact_key의 표시 이름("한식") — constraints.FACT_LABELS
    wants: bool | None = None  # 이 특징이 있는 장소를 원하는가(#228). None = 모름
    # 후보를 거르거나 점수 매기는 데 실제로 쓰이는 줄인가(#720, #740) — core.evidence_line_use가 파이프라인과 같은 기준으로 정한다.
    # 끈 줄(is_active=false)도 켜면 쓰이는지를 보인다. 쓰이지 않으면 이유(not_enforced_reason)가 따라온다. 응답에는 항상 채워 내려 준다.
    enforced: bool | None = None
    not_enforced_reason: Literal["no_key", "no_direction", "not_for_category", "off_season"] | None = None
    # 쓰이는 줄이 후보를 빼는가(true, hard와 접근성 필요 조건) 순위만 낮추는가(false, 취향 줄)(#1260). 쓰이지 않으면 null.
    # core.evidence_line_use(LineUse.filters_candidates)가 정한다.
    filters_candidates: bool | None = None
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


class MemberCondition(BaseModel):
    fact_key: str
    fact_label: str | None = Field(default=None, max_length=30)   # 서버가 주는 표시 이름만. 사용자 글은 담지 않는다(#717)
    evidence_line_id: str | None = None   # 직접 쓴 근거 줄의 id, ♥에서 나왔으면 None
    status: Literal["met", "unmet", "needs_check"]


class MemberFulfillmentEntry(BaseModel):
    user_id: str
    display_name: str | None = None  # 서버는 채우지 않는다. FE가 user_id로 구성원 목록에서 찾는다(#762)
    satisfied: bool
    conditions: list[MemberCondition] | None = None   # 조건별 상태(#805). 없으면 구버전 서버 — satisfied만 쓴다


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
    place_url: str | None = Field(default=None, max_length=2000)  # 「카카오맵에서 보기」(places.api.place_link, #798)
    naver_url: str | None = Field(default=None, max_length=2000)  # 「네이버 지도에서 보기」(places.api.naver_place_link, #1513)
    visibility: Literal["private", "published"]
    published_pin_id: str | None = None
    permissions: Permissions


# 후보가 이 값 미만이면 결과가 적다 — RecommendResult.external_search를 싣는 기준(#798). agent의 추천 막힘 기준
# (agent.constants.BLOCKED_RUN_MAX_RESULTS)도 이 값을 받는다(#800). recommend.api가 아니라 여기 두는 이유: agent.constants는
# auth 경로(auth.service → agent.api)에 있어 recommend.api를 import하면 순환한다.
FEW_RESULTS = 3


class FunnelEntry(BaseModel):
    key: str | None = None   # FUNNEL_STAGES 키. 표에 없는 옛 라벨은 None(#1146)
    label: str
    removed_count: int


class RecommendResult(BaseModel):
    run_id: str
    funnel: list[FunnelEntry]
    regions: list[Region]
    candidates: list[Candidate]
    external_search: ExternalSearch | None = None  # 후보가 FEW_RESULTS곳 미만일 때만(#798)
    # #845: 이번 결과에 실제로 쓴 근거(실행 시점 스냅샷), 쓰이는 사유 근거가 0개인지, 마지막 실행이 새로 찾은 수.
    # 스냅샷이 없는 예전 run에는 세 필드 모두 없다.
    applied_evidence: list[EvidenceLine] | None = None
    no_applied_conditions: bool | None = None
    new_count: int | None = Field(default=None, ge=0)

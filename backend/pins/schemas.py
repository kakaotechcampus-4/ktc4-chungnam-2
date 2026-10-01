"""
docs/api-spec.yaml의 pins 태그 스키마와 1:1로 맞춘다.
Pin의 place_name은 생성 요청(PinCreateRequest.place_name)에서 그대로 저장한다(루트 결정,
2026-09-23). checks는 게시(pins.api.create_ai_pin) 시점에 candidate.checks를 그대로 복사해
채운다(#57/#124 결정, 가드레일 5). price_bucket/created_by_display_name/source_run_id는
여전히 places/auth/recommend 모듈 연동이 더 필요해 채울 수 없다 — Optional로 두고 라우터에서
response_model_exclude_none으로 생략한다.

Permissions는 여기서 정의하지 않는다 — Pin·EvidenceLine·ShortlistItem이 공유하는 스키마라
authz가 소유한다(#56 이관, mentor-review-plan.md). pins는 authz의 것을 그대로 쓴다.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_serializer

from authz.schemas import Permissions

Category = Literal["음식점", "카페", "숙소", "관광지", "기타"]
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


class MemberFulfillmentEntry(BaseModel):
    user_id: str
    display_name: str | None = None
    satisfied: bool


class MemberFulfillment(BaseModel):
    """구성원 충족 집계(가드레일 5) — 값은 recommend가 채워 게시 시점에 복사된다."""

    satisfied: int = Field(ge=0)
    total: int = Field(ge=0)
    by_member: list[MemberFulfillmentEntry] | None = None


class PlaceSource(BaseModel):
    provider: Literal["kakao", "naver", "google"]
    url: str | None = None


class ReactionSummary(BaseModel):
    like: int = 0
    neutral: int = 0
    against: int = 0


class PinCreateRequest(BaseModel):
    """place_id·place_name·lat·lng·category는 **저장하지 않는 매칭 힌트**다(#191, 스펙 PinCreateRequest).
    서버가 같은 자체 DB 장소를 찾아 그 장소의 값으로 핀을 만든다. v1은 source=search만 받는다."""

    category: Category
    source: PinSource = "search"
    link_url: str | None = None
    place_id: str
    place_name: str = Field(max_length=100)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Reaction(BaseModel):
    """None인 필드(reason_text·reason_chip_ids·display_name)는 응답에서 생략한다 — 라우터가
    response_model_exclude_none을 쓴다(스펙: 없으면 필드 생략). display_name은 GET /reactions 전용."""

    pin_id: str
    user_id: str
    type: ReactionKind
    reason_text: str | None = None
    reason_chip_ids: list[str] | None = None
    display_name: str | None = None


class Pin(BaseModel):
    id: str
    map_id: str
    category: Category
    kind: PinKind
    visibility: Literal["public", "private"]
    lat: float
    lng: float
    place_name: str | None = None
    place_url: str | None = None
    created_by: str
    created_by_display_name: str | None = None
    price_bucket: PriceBucket | None = None
    checks: list[Check] | None = None
    source_run_id: str | None = None
    reason: str | None = None
    member_fulfillment: MemberFulfillment | None = None
    place_source: PlaceSource | None = None
    # 요청자 본인의 반응 — 없으면 null(스펙). 다른 구성원에게 새면 안 되는 값이라 SSE 페이로드엔
    # 싣지 않는다(core.pin_*_event가 제외). 직렬화 때 null을 유지하는 건 아래 serializer.
    my_reaction: Reaction | None = None
    reaction_summary: ReactionSummary = Field(default_factory=ReactionSummary)
    permissions: Permissions

    @model_serializer(mode="wrap")
    def _keep_my_reaction_null(self, handler, info):
        """response_model_exclude_none이 my_reaction: null까지 지우면 "없으면 null"(스펙)이 깨진다."""
        data = handler(self)
        excluded = info.exclude or ()
        if info.exclude_none and "my_reaction" not in excluded:
            data["my_reaction"] = data.get("my_reaction")
        return data


class FilterCounts(BaseModel):
    by_category: dict[str, int]
    by_kind: dict[str, int]


class ReactionRequest(BaseModel):
    type: ReactionKind
    reason_text: str | None = Field(default=None, max_length=140)
    reason_chip_ids: list[str] | None = None


class Error(BaseModel):
    code: str
    message: str
    detail: dict | None = None

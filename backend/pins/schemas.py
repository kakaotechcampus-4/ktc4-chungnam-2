"""
docs/api-spec.yaml의 pins 태그 스키마와 1:1로 맞춘다.
Pin의 place_name은 생성 요청(PinCreateRequest.place_name)에서 그대로 저장한다(루트 결정,
2026-09-23). checks는 게시(pins.api.create_ai_pin) 시점에 candidate.checks를 그대로 복사해
채운다(#57/#124 결정, 가드레일 5). created_by_display_name/source_run_id는
여전히 places/auth/recommend 모듈 연동이 더 필요해 채울 수 없다 — Optional로 두고 라우터에서
response_model_exclude_none으로 생략한다.

Permissions는 여기서 정의하지 않는다 — Pin·EvidenceLine·ShortlistItem이 공유하는 스키마라
authz가 소유한다(#56 이관, mentor-review-plan.md). pins는 authz의 것을 그대로 쓴다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from authz.schemas import Permissions
from common import categories

Category = Literal[categories.all_categories()]  # 스펙의 Category(common/categories.py, #280)
PinKind = Literal["일반", "AI추천", "확정"]
LabelConfidence = Literal["known", "unknown"]
ReactionKind = Literal["like", "against"]
PinSource = Literal["link", "search", "coordinate"]   # PinCreateSearch.source — 실시간 핀은 PinCreateLive
PinStorage = Literal["db", "live"]   # Pin.source — 자체 DB 장소를 가리키는 핀(db) / 실시간 핀(live, #382)


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
    provider: Literal["kakao", "naver", "google", "permit", "tourapi"]
    url: str | None = None


class ReactionSummary(BaseModel):
    like: int = 0
    against: int = 0


class PinCreateLive(BaseModel):
    """실시간 핀(#382, 스펙 PinCreateLive) — 자체 DB에 없는 장소. 저장하는 카카오 값은 장소 ID뿐이고
    이름·좌표는 받지도 않는다(extra=forbid → 422, 카카오 응답은 저장 불가 #53)."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["live"]
    category: Category
    kakao_place_id: str = Field(min_length=1, max_length=100)
    search_query: str = Field(min_length=1, max_length=100)
    memo: str | None = Field(default=None, max_length=200)


class PinCreateSearch(BaseModel):
    """place_id·place_name·lat·lng·category는 **저장하지 않는 매칭 힌트**다(#191, 스펙 PinCreateSearch).
    서버가 같은 자체 DB 장소를 찾아 그 장소의 값으로 핀을 만든다. source를 생략하거나 search로 보낸다."""

    category: Category
    source: PinSource = "search"
    link_url: str | None = None
    place_id: str = Field(max_length=100)
    place_name: str = Field(max_length=100)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


# 스펙 PinCreateRequest = oneOf(PinCreateSearch, PinCreateLive). source로 갈린다 — live는 extra=forbid라
# 이름·좌표가 섞이면 live에서 떨어지고, search는 source=live를 받지 않아 둘 다 실패한다(422).
PinCreateRequest = PinCreateLive | PinCreateSearch


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
    lat: float | None = None   # live 핀(#382)에는 없다 — 서버가 카카오 좌표를 저장하지 않는다
    lng: float | None = None
    source: PinStorage = "db"
    memo: str | None = None
    kakao_place_id: str | None = None   # live 핀만
    search_query: str | None = None     # live 핀만
    place_name: str | None = None
    place_url: str | None = None
    created_by: str
    created_by_display_name: str | None = None
    created_at: datetime | None = None   # 지도에 올라온 시각(AI 추천 핀은 「지도에 올리기」 시각) — 서버가 채우면 항상 있다
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


class ReasonChip(BaseModel):
    """반대 사유 칩(#60). fact_key가 없으면(「공통」 칩, 가격 칩 #423) 응답에서 생략한다 — 라우터의 response_model_exclude_none.
    wants(docs/constraints.md 칩 표의 방향, #412)는 서버가 근거 줄을 만들 때만 쓰고 응답에는 내보내지 않는다
    (api-spec.yaml ReasonChip에 없다)."""

    id: str
    label: str
    fact_key: str | None = None
    wants: bool | None = Field(default=None, exclude=True)


class FilterCounts(BaseModel):
    members_with_opinion: int | None = None
    members_total: int | None = None
    by_category: dict[str, int]
    by_kind: dict[str, int]


class ReactionRequest(BaseModel):
    type: ReactionKind
    reason_text: str | None = Field(default=None, max_length=140)
    # docs/api-spec.yaml ReactionRequest — 최대 10개, 칩 하나는 50자까지. 내용이 비었는지는
    # core.validate_reaction이 본다(공백·제로폭만 있는 칩은 길이만으론 못 거른다).
    reason_chip_ids: list[Annotated[str, Field(max_length=50)]] | None = Field(default=None, max_length=10)


class Error(BaseModel):
    code: str
    message: str
    detail: dict | None = None

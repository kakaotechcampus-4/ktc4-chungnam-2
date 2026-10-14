"""
두 종류의 스키마를 둔다(docs/agent-v2.md 4절).

1. API 스키마 — docs/api-spec.yaml의 Agent*·RunAdvice와 1:1. FE는 서버가 렌더한 문장만 받는다. claims, 슬롯 원문,
   fingerprint, resolved_by 같은 서버 내부 값은 여기 없다(명세 14절).
2. 모델 출력 스키마 — 명세 11.1. llm 쪽 agent 함수의 구조화 출력 스키마이자 deps.py 고정 응답 스텁의 반환 타입이다.
   모델은 숫자를 문장에 직접 쓰지 않고 claim을 슬롯({c1.value}, {c3})으로 가리킨다. 검증과 렌더는 core.py(M1)가 한다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_serializer

from common import categories

Category = Literal[categories.all_categories()]  # 스펙의 Category(common/categories.py, #280)

# ---------- API 스키마 (docs/api-spec.yaml agent 태그) ----------

AgentDiagnosis = Literal["stall", "split", "no_reaction", "category_gap"]
ActionType = Literal["open_recommend", "show_pins", "search_place", "open_route", "widen_radius", "open_evidence"]
ConflictType = Literal["same_axis", "different_axes", "unclear"]
RunAdviceKind = Literal["radius", "soft_relax", "vague_reason", "exhausted"]


class AgentAdviceLine(BaseModel):
    text: str = Field(max_length=300)
    is_guess: bool  # false=확인된 것, true=AI 조언(추정)


class AgentActionParams(BaseModel):
    """type마다 쓰는 것만 채운다. 스펙의 params 키는 null을 받지 않아서 채우지 않은 키는 직렬화에서 뺀다.
    응답 전체에 exclude_none을 걸면 null이 필수인 칸(AgentSuggestion.category 등)까지 빠지므로 여기서만 뺀다."""
    category: Category | None = None
    pin_ids: list[str] | None = None
    unseen_only: bool | None = None
    run_id: str | None = None
    evidence_line_ids: list[str] | None = None  # open_evidence: 요청자 본인이 쓴 줄만

    @model_serializer(mode="wrap")
    def _drop_unset(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class AgentAction(BaseModel):
    index: int = Field(ge=0)  # accept 요청의 action_index
    type: ActionType
    label: str = Field(max_length=40)
    params: AgentActionParams


class AgentConflictAxis(BaseModel):
    label: str
    like_side: str | None
    against_side: str | None


class AgentAnalysis(BaseModel):
    conflict_type: ConflictType
    axes: list[AgentConflictAxis]


class AgentSuggestion(BaseModel):
    id: str
    diagnosis: AgentDiagnosis
    category: Category | None
    title: str = Field(max_length=100)
    analysis: AgentAnalysis | None = None
    advice: list[AgentAdviceLine]
    actions: list[AgentAction]
    created_at: datetime
    expires_at: datetime


class AgentSummaryItem(BaseModel):
    fact_key: str | None = None
    label: str
    member_count: int = Field(ge=1)  # 한 사람이 여러 번 말해도 1


class AgentSplitPref(BaseModel):
    fact_key: str
    label: str
    want_count: int = Field(ge=1)
    avoid_count: int = Field(ge=1)


class AgentVagueFixable(BaseModel):
    count: int = Field(ge=0)
    requests: list[str]


class AgentNotFiltered(BaseModel):
    count: int = Field(ge=0)
    notices: list[str]  # 고정 안내만. 원문은 싣지 않는다


class AgentSummary(BaseModel):
    category: Category
    must_keep: list[AgentSummaryItem]
    common_prefs: list[AgentSummaryItem]
    split_prefs: list[AgentSplitPref]
    vague_fixable: AgentVagueFixable
    not_filtered: AgentNotFiltered
    updated_at: datetime


class AgentSettings(BaseModel):
    enabled: bool
    updated_by: str | None = None  # 한 번도 바꾸지 않았으면(기본값 켜짐) null
    updated_at: datetime | None = None


class AgentSettingsRequest(BaseModel):
    enabled: bool


class AgentState(BaseModel):
    settings: AgentSettings
    active_suggestion: AgentSuggestion | None  # 모드가 꺼져 있거나 shadow면 null
    has_unseen: bool
    summaries: list[AgentSummary]


class AgentAcceptRequest(BaseModel):
    action_index: int = Field(ge=0)


class AgentAcceptResponse(BaseModel):
    action: AgentAction


class RunAdvice(BaseModel):
    run_id: str
    kind: RunAdviceKind
    advice: list[AgentAdviceLine]
    actions: list[AgentAction]  # widen_radius, open_evidence만


# ---------- 모델 출력 스키마 (명세 11.1) ----------

Decision = Literal["suggest", "silent", "unknown"]


class CountClaim(BaseModel):
    id: str  # c1, c2 ...
    kind: Literal["count"]
    subject: Literal["pin", "category", "map"]
    subject_id: str | None  # pin_id 또는 카테고리 이름, map이면 None
    metric: Literal["like", "against", "unseen", "confirmed", "pins"]  # 반응은 2종 (#360)
    value: int


class QuoteClaim(BaseModel):
    id: str
    kind: Literal["quote"]
    reaction_id: str
    text: str  # 대조용. 화면에는 DB 원문을 렌더한다


class RefClaim(BaseModel):
    id: str
    kind: Literal["ref"]
    object: Literal["pin", "reaction", "place"]
    ref_id: str


class ToolClaim(BaseModel):
    id: str
    kind: Literal["tool_result"]
    call_id: str  # agent가 매긴 도구 호출 id
    path: str  # 결과 안의 경로. 예: "after"
    value: int | float | str | bool


Claim = Annotated[CountClaim | QuoteClaim | RefClaim | ToolClaim, Field(discriminator="kind")]


class AdviceLine(BaseModel):
    text: str  # 슬롯 {c1.value}, {c3}만 허용. 숫자 직접 금지
    basis: list[str]  # claim id
    is_guess: bool


class Action(BaseModel):
    type: ActionType
    category: str | None = None
    pin_ids: list[str] | None = None
    basis: list[str]


# Stance와 모델이 내던 Conflict는 없다(2026-10-15). 키와 방향은 ②가, 충돌 종류는 코드가 정한다(명세 6.3, 8.1).


class DiagnosisOutput(BaseModel):
    decision: Decision
    diagnosis: Literal["stall", "split"]
    signal_id: str
    claims: list[Claim]
    advice: list[AdviceLine]
    actions: list[Action]


class PriorityItem(BaseModel):
    signal_id: str
    reason: str


class PriorityOutput(BaseModel):
    order: list[PriorityItem]


class SummaryOutput(BaseModel):
    """칸 나누기와 개수는 코드가 한다(명세 8절). 모델은 vague_fixable 사유에 붙일 구체화 요청 문장만 쓴다."""
    decision: Decision
    claims: list[Claim]  # 요청 문장이 가리키는 reaction (RefClaim)
    requests: list[AdviceLine]


class RunAdviceOutput(BaseModel):
    decision: Decision
    kind: RunAdviceKind
    claims: list[Claim]
    advice: list[AdviceLine]
    actions: list[Action]  # widen_radius, open_evidence만

"""
두 종류의 스키마를 둔다(docs/agent-v2.md 4절).

1. API 스키마 — docs/api-spec.yaml의 Agent*·RunAdvice와 1:1. FE는 서버가 렌더한 문장만 받는다. claims, 슬롯 원문,
   fingerprint, resolved_by 같은 서버 내부 값은 여기 없다(명세 14절).
2. 모델 출력 스키마 — 명세 11.1. 정의는 llm/schemas.py에 있고 여기서는 가져다 쓴다(#533). 모델은 숫자를 문장에
   직접 쓰지 않고 claim을 슬롯({c1.value}, {c3})으로 가리킨다. 검증과 렌더는 core.py가 한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_serializer

from common import categories
from llm.schemas import (  # noqa: F401 — 모델 출력 스키마(11.1)의 정본을 다시 연다. 아래 "모델 출력 스키마" 절
    Action,
    AdviceLine,
    AgentCallFailed,
    AgentDecision as Decision,
    AgentReply,
    AgentUsage,
    Claim,
    CountClaim,
    DiagnosisOutput,
    QuoteClaim,
    RefClaim,
    RunAdviceOutput,
    ToolClaim,
)

Category = Literal[categories.all_categories()]  # 스펙의 Category(common/categories.py, #280)

# ---------- API 스키마 (docs/api-spec.yaml agent 태그) ----------

AgentDiagnosis = Literal["stall", "split", "no_reaction", "category_gap"]
ActionType = Literal["open_recommend", "show_pins", "search_place", "open_route", "widen_radius", "open_evidence"]
ConflictType = Literal["same_axis", "different_axes", "unclear"]
RunAdviceKind = Literal["radius", "soft_relax", "vague_reason", "exhausted"]


class AdviceSegment(BaseModel):
    """문장 조각(#717). text는 에이전트 문장, quote는 구성원 사유 글 중 검증한 범위만, pin은 핀 이름. 스펙의 reaction_id와
    pin_id는 null을 받지 않아서 채우지 않은 키는 직렬화에서 뺀다(AgentActionParams와 같은 방식)."""
    kind: Literal["text", "quote", "pin"]
    text: str = Field(max_length=300)
    reaction_id: str | None = None   # kind=quote일 때만
    pin_id: str | None = None        # kind=pin일 때만

    @model_serializer(mode="wrap")
    def _drop_unset(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class AgentAdviceLine(BaseModel):
    segments: list[AdviceSegment] = Field(min_length=1)
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
# 정의는 llm/schemas.py 한 곳이다(#532). 사본을 두면 Gateway 반환 타입이 어긋나서 agent는 가져다 쓴다(다른 모듈 schemas.py
# 직접 import는 허용, #113). Claim에는 discriminator가 없다 — 엘리스 API가 구조화 출력의 oneOf를 거절한다(#532).
# RunAdviceOutput은 #587에서 llm/schemas.py로 옮겼다. SummaryOutput은 요약 문장이 고정 문구라(2026-10-16) llm 함수가 없어
# 여기 남아 있다. #588에서 모델이 필요하다고 보면 그때 옮긴다.

class SummaryOutput(BaseModel):
    """칸 나누기와 개수는 코드가 한다(명세 8절). 모델은 vague_fixable 사유에 붙일 구체화 요청 문장만 쓴다."""
    decision: Decision
    claims: list[Claim]  # 요청 문장이 가리키는 reaction (RefClaim)
    requests: list[AdviceLine]


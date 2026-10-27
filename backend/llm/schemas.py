"""backend/llm 구조화 출력 스키마.

정본:
- docs/data-model.md `evidence_lines` / `place_facts` 테이블
- docs/constraints.md `fact_key` 레지스트리 (값 변경은 루트만 — 여기서 새 fact_key를 만들지 않는다)
- docs/api-spec.yaml `LabelConfidence`(known/unknown)와 1:1

모델 호출(backend/llm/CLAUDE.md)에 대응하는 스키마만 담는다:
  ②    PlanningOutput (사유 → 실격/선호/반경 구조화)
  ③-a-1 PlaceFactLabel (장소 라벨링)
  ③-b   RankedCandidate (선호 순위)
  v2 에이전트 DiagnosisOutput, AgentCallFailed (docs/agent-v2.md 11.1, #532), AgentUsage·AgentReply(#564).
       PriorityOutput은 #582에서, RunAdviceOutput은 #749에서 지웠다(우선순위와 추천 막힘 조언은 agent의 코드)
  v2 동선 에이전트 CourseTurn (drafts/agent-route-v2.md 11.1, #334), 목표 세우기 CourseGoalSet, 지휘 턴 CourseDirectTurn
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, Optional, TypeVar, Union, get_args

from pydantic import BaseModel, ConfigDict, model_validator

# docs/constraints.md `fact_key` 레지스트리와 같다 — backend/integration/test_llm_fact_key_contract.py가
# 양방향으로 강제한다(문서에만 키를 넣으면 CI 실패). 새 키는 루트가 문서에 먼저 넣고, 여기와
# prompts.FACT_KEY_MEANINGS에 같이 넣는다. 값 변경은 루트만이다.
# within_radius / is_open은 표에서도 "코드 판정"으로 분류되어 라벨링(③-a-1)·사유 구조화(②) 대상이
# 아니므로 후보에서 제외한다. 숙소는 AI 추천 대상이 아니라 숙소 전용 키(capacity_min)는 없다(#145).
FactKey = Literal[
    # 공통
    "pet_friendly",
    # 음식점
    "spicy_focused",
    "oily_focused",
    "wait_short",
    "cuisine_korean",
    "cuisine_chinese",
    "cuisine_japanese",
    "cuisine_western",
    "cuisine_bunsik",
    "cuisine_chicken_pub",
    "cuisine_bbq",
    "cuisine_gopchang",
    "cuisine_foreign",
    "cuisine_raw_fish",
    "cuisine_buffet",
    "spacious",
    "long_established",
    "parking_available",
    "vegetarian_friendly",
    "franchise",
    # 카페 전용 (#263)
    "bakery",
    "serves_alcohol",
    "open_late",
    # 카페·관광지 공통
    "is_crowded_large",
    "quiet",
    "comfortable_seat",
    "local_flavor",
    # 관광지 — 성격
    "restful",
    "good_view",
    "photogenic",
    "night_view",
    "date_spot",
    "hallyu_related",
    "traditional_hanok",
    "modern_architecture",
    "religious_site",
    # 관광지 — 공간
    "is_indoor",
    "is_outdoor",
    # 관광지 — 자연
    "mountain",
    "waterside",
    "forest",
    "flower_garden",
    "seaside",
    # 관광지 — 활동
    "walkable",
    "hiking",
    "cycling",
    "hands_on",
    "exhibition",
    "performance",
    "shopping",
    "heritage_tour",
    # 관광지 — 동반
    "family_friendly",
    "kid_friendly",
    "accessible",
    # 관광지 — 계절
    "cherry_blossom",
    "autumn_foliage",
    "water_play",
    "winter_spot",
]
FACT_KEYS: tuple[str, ...] = get_args(FactKey)

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
    # 이 특징(fact_key)이 있는 장소를 원하는가 (docs/constraints.md "사유의 방향(wants)과 실격", #228).
    # true="한식 먹자", false="한식 말고". 모르면 None. fact_key가 없으면 반드시 None.
    wants: Optional[bool] = None
    circle_anchor_pin_id: Optional[str] = None
    circle_radius_m: Optional[int] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _wants_needs_fact_key(self) -> "EvidenceLine":
        # 방향은 키가 있을 때만 의미가 있다. 키 없이 wants가 들어와도 예외로 ② 전체를 무너뜨리지 않고 버린다.
        if self.fact_key is None:
            self.wants = None
        return self


class PlannedCondition(BaseModel):
    """② 응답 — 사유 글에서 읽은 조건 하나(키와 방향). 근거 줄 하나가 된다(#419)."""

    fact_key: FactKey
    wants: Optional[bool] = None


class PlannedReason(BaseModel):
    """② 응답 — 입력 글 한 줄에 대한 결과. index·text는 입력과 맞는지 대조하는 데만 쓴다.

    conditions는 0개 이상이다 — 비면 키 없는 줄 하나, 여럿이면 조건마다 줄 하나(#419).
    badge·author 같은 나머지 필드는 받지 않는다 — 모델이 바꿀 수 없는 값이라 에코할 이유가 없다."""

    index: int
    text: str
    conditions: list[PlannedCondition]
    circle_radius_m: Optional[int] = None


class PlanningOutput(BaseModel):
    """② 사유 → 실격/선호/반경 구조화 출력. 입력 글마다 PlannedReason 하나."""

    reasons: list[PlannedReason]


class PlaceFactLabel(BaseModel):
    """③-a-1 장소 라벨링 출력 (docs/api-spec.yaml LabelConfidence와 동일 값셋).

    confidence=unknown일 때 value를 지어내지 않는다 — 반드시 None이어야 한다
    (backend/llm/CLAUDE.md "넘지 말 것", 가드레일 8·9). evidence도 마찬가지다 —
    판정 근거가 없는데 근거 텍스트만 지어내면 안 되므로 unknown이면 evidence도 None이어야 한다.
    unknown_policy 적용·실격 여부 판단은 이 스키마의 책임이 아니다 — recommend가 한다(가드레일 7).
    """

    fact_key: FactKey
    value: Optional[Union[bool, str, int]] = None
    confidence: Confidence
    evidence: Optional[str] = None

    @model_validator(mode="after")
    def _unknown_must_not_have_value(self) -> "PlaceFactLabel":
        if self.confidence == "unknown" and self.value is not None:
            raise ValueError("confidence=unknown인데 value가 채워져 있다 — 값을 지어내면 안 된다")
        if self.confidence == "unknown" and self.evidence is not None:
            raise ValueError("confidence=unknown인데 evidence가 채워져 있다 — 근거를 지어내면 안 된다")
        if self.confidence == "known" and self.value is None:
            raise ValueError("confidence=known이면 value가 있어야 한다")
        return self


class RankedCandidate(BaseModel):
    """③-b 선호 순위 채점 출력. 입력은 이미 실격 통과분이며, 이 스키마는 순위만 매긴다."""

    place_id: str
    rank: int
    member_comment: Optional[str] = None  # 근거 없으면 None (5-7-1) — 지어내지 않는다


# ---------- v2 계획 보조 에이전트 — 모델 출력 (docs/agent-v2.md 11.1, #532) ----------
# agent_diagnose의 구조화 출력 스키마다. agent/schemas.py(#513)의 같은 이름 클래스와 필드가 같다 —
# 하나로 합치는 일(agent가 여기서 가져가기)은 #533이 한다. 모델은 숫자를 문장에 직접 쓰지 않고 claim을 슬롯({c1.value},
# {c3})으로 가리킨다. 검증과 렌더는 agent의 core가 한다(명세 11.2) — 여기서는 스키마 검증까지만이다.
# Stance와 모델이 내던 Conflict는 없다(2026-10-15). 키와 방향은 ②가, 충돌 종류는 코드가 정한다(명세 6.3, 8.1).

AgentDecision = Literal["suggest", "silent", "unknown"]
AgentActionType = Literal["open_recommend", "show_pins", "search_place", "open_route", "widen_radius", "open_evidence"]


class CountClaim(BaseModel):
    id: str  # c1, c2 ...
    kind: Literal["count"]
    subject: Literal["pin", "category", "map"]
    subject_id: Optional[str]  # pin_id 또는 카테고리 이름, map이면 None
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
    call_id: str  # 도구 호출 id(t1, t2 …). agent_diagnose가 매겨 tool_runner와 모델에 같은 값을 준다
    path: str  # 결과 안의 경로. 예: "after"
    value: Union[int, float, str, bool]


# discriminator를 걸지 않는다 — 걸면 JSON 스키마가 oneOf가 되고, 엘리스 API strict 구조화 출력은 oneOf를 400으로 거절한다
# ("'oneOf' is not permitted", 2026-10-15 확인). 일반 Union은 anyOf라 받는다. kind가 클래스마다 다른 Literal이라 검증 결과는 같다.
Claim = Union[CountClaim, QuoteClaim, RefClaim, ToolClaim]


class AdviceLine(BaseModel):
    text: str  # 슬롯 {c1.value}, {c3}만 허용. 숫자 직접 금지
    basis: list[str]  # claim id
    is_guess: bool  # 추정 문장이면 True


class Action(BaseModel):
    type: AgentActionType
    category: Optional[str] = None
    pin_ids: Optional[list[str]] = None
    basis: list[str]


class DiagnosisOutput(BaseModel):
    decision: AgentDecision
    diagnosis: Literal["stall", "split"]
    signal_id: str
    claims: list[Claim]
    advice: list[AdviceLine]
    actions: list[Action]


AgentFailureReason = Literal["invalid_schema", "timeout", "call_failed"]


class AgentCallFailed(BaseModel):
    """agent 호출이 실패했다는 결과. 재요청하지 않고 이것을 돌려준다 — agent가 침묵으로 처리한다
    (명세 2절 10번). 예외로 올리지 않는 이유: 백그라운드 관찰에서는 실패가 정상 경로의 하나다.

    reason: invalid_schema(응답이 스키마에 맞지 않음, 빈 응답, 도구 인자 깨짐), timeout, call_failed(그 밖의 호출 실패·거절,
    도구 상한을 넘긴 뒤에도 도구를 부름). detail은 예외 클래스명과 고정 문구만이다 — 사유 원문·응답 본문은 넣지 않는다(#390).
    """

    reason: AgentFailureReason
    detail: str


class AgentUsage(BaseModel):
    """agent 호출 한 번(agent_diagnose)이 쓴 모델 사용량(#564). agent가 agent_runs의 model,
    prompt_version, tokens_in, tokens_out에 채운다. 토큰은 그 호출 안의 모든 왕복의 합이다(진단은 도구 왕복마다 한 번).

    모델에 요청을 보냈으면 model과 prompt_version이 찬다(응답 전에 실패해도). 고정 응답 스텁이나 요청 전에 실패한 호출
    (설정 누락)은 None과 0이다. 응답 안에서 스키마 검증이 실패한 왕복은 SDK가 사용량을 넘기지 않아 토큰에 들어가지 않는다."""

    model: Optional[str] = None
    prompt_version: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0


AgentResultT = TypeVar("AgentResultT")


@dataclass(frozen=True)
class AgentReply(Generic[AgentResultT]):
    """agent 호출의 결과와 사용량. 실패(AgentCallFailed)여도 usage에는 그때까지 쓴 사용량이 있다(#564)."""

    result: Union[AgentResultT, AgentCallFailed]
    usage: AgentUsage


# ---- v2 동선 에이전트 턴 (#334, drafts/agent-route-v2.md 7·11절) ----
# 모델은 턴마다 도구 하나를 고른다. 매개변수는 전부 별칭(p1, d1, t1)이다 — 좌표·날짜·장소 id는 모델이 만들 수 없다.
# agent/course가 이 스키마를 그대로 쓴다(agent.course.schemas). discriminator를 걸지 않는다(위 Claim과 같은 이유, oneOf 금지).
# 클래스마다 type·tool이 다른 Literal이고 extra="forbid"라 Union 검증 결과는 discriminator와 같다.


class _CourseStrict(BaseModel):
    # 모르는 필드가 오면 실패시킨다 — 모델이 스키마 밖 값을 끼워 넣어도 조용히 버리지 않는다.
    model_config = ConfigDict(extra="forbid")


class CourseSwap(_CourseStrict):
    """두 장소의 자리를 바꾼다. 같은 날 안이든 다른 날 사이든 된다."""
    type: Literal["swap"]
    a: str
    b: str


class CourseMoveDay(_CourseStrict):
    """장소를 다른 날로 옮긴다(이월). position이 null이면 코드가 그날 이동이 가장 짧은 자리에 넣는다."""
    type: Literal["move_day"]
    place: str
    to_day: str
    position: Optional[int] = None


class CourseReorderDay(_CourseStrict):
    """그날의 장소 순서를 통째로 정한다. 그날 장소의 완전한 순열이어야 한다."""
    type: Literal["reorder_day"]
    day: str
    places: list[str]


CourseMove = Union[CourseSwap, CourseMoveDay, CourseReorderDay]


class CourseGetOpeningHours(_CourseStrict):
    tool: Literal["get_opening_hours"]
    place: str


class CourseFindOpenDays(_CourseStrict):
    tool: Literal["find_open_days"]
    place: str


class CourseEstimateTravel(_CourseStrict):
    tool: Literal["estimate_travel"]
    from_place: str
    to_place: str


class CourseTryMove(_CourseStrict):
    tool: Literal["try_move"]
    move: CourseMove


class CourseCommitMove(_CourseStrict):
    tool: Literal["commit_move"]
    trial_id: str


class CourseRevert(_CourseStrict):
    tool: Literal["revert"]
    to_step: int


class CourseFinish(_CourseStrict):
    tool: Literal["finish"]
    reason_code: Literal["solved", "no_progress", "budget"]


CourseToolCall = Union[
    CourseGetOpeningHours, CourseFindOpenDays, CourseEstimateTravel, CourseTryMove, CourseCommitMove, CourseRevert,
    CourseFinish,
]


class CoursePlanStep(_CourseStrict):
    step: int
    intent: str


class CourseTurn(_CourseStrict):
    """모델 호출 한 번의 출력. 생각·계획·교훈은 상태를 바꾸지 않는다 — 상태는 action(도구)으로만 바뀐다.
    계획 길이 상한(5단계)은 strict 스키마에 maxItems를 넣지 않고 agent가 자른다."""
    thought: str
    plan: list[CoursePlanStep] = []
    lesson: Optional[str] = None
    action: CourseToolCall


# ---- 목표 세우기와 지휘 턴 (#334, drafts/course-agent-pivot.md) ----
# 모델은 코스를 직접 고치지 않는다. 요청 한 줄을 목표로 바꾸고(CourseGoalSet), 코드 최적화 도구를 불러 후보를 고른다(CourseDirectTurn).
# 목표 점수·충족 판정과 후보 계산은 agent/course가 코드로 한다. 평평한 객체만 쓴다(oneOf 금지).


class CourseGoal(_CourseStrict):
    kind: Literal["day_indoor", "night_end", "daily_walk_low", "day_light", "place_on_day", "together", "day_has"]
    day: Optional[str] = None            # d1 … (day_indoor, night_end, day_light, place_on_day, day_has)
    places: list[str] = []               # p1 … (place_on_day 1개, together 2개)
    tag: Optional[str] = None            # day_has만: 고정 목록(performance, exhibition, night_view, indoor, shopping, walkable, kid_friendly, heritage). 코드가 대조한다
    source: Literal["request", "reason"] = "request"    # reason(구성원 사유)은 이번 범위 밖 — 자리만 둔다
    quote: str = ""                      # source=request: 근거가 된 요청 문장 조각(코드가 원문 부분 문자열인지 대조)
    reaction_ids: list[str] = []         # source=reason: 근거 사유 별칭(r1 …). 이번 범위 밖


class CourseGoalSet(_CourseStrict):
    goals: list[CourseGoal]
    unmatched: list[str]                 # 목표로 못 바꾼 요청 조각(원문 부분 문자열). 화면에 "반영하지 못했어요"


class CourseLockSpec(_CourseStrict):
    place: str
    day: str


class CourseOptimize(_CourseStrict):
    """코드 최적화를 부른다. priority는 목표 id 순서(앞이 더 중요), locks는 이번 호출에서 날짜를 고정할 장소."""
    tool: Literal["optimize"]
    priority: list[str]
    locks: list[CourseLockSpec]


class CourseLockCall(_CourseStrict):
    """장소를 한 날에 고정한다. 한 번 고정하면 풀 수 없다."""
    tool: Literal["lock"]
    place: str
    day: str


class CourseAskRequester(_CourseStrict):
    """요청자에게 묻는다. 문구는 코드 템플릿이다 — 종류와 대상만 고른다."""
    tool: Literal["ask_requester"]
    kind: Literal["pick_course", "ask_closed_day", "choose_day", "split_day"]
    subject: Optional[str] = None        # ask_closed_day: 장소 별칭, choose_day: 쉬는 날에 걸린 목표 id, split_day: 이동 위반이 남은 날 별칭
    options: list[str] = []              # pick_course: 후보 id(c1, c2 …), choose_day: 여는 날 별칭, split_day: 나누기 선택지 id(m1, m2 …) — 첫 번째가 제안하는 기본값


class CourseDirectFinish(_CourseStrict):
    tool: Literal["finish"]
    candidate_id: str


CourseDirectCall = Union[CourseOptimize, CourseLockCall, CourseAskRequester, CourseDirectFinish]


class CourseDirectTurn(_CourseStrict):
    """지휘 턴 한 번의 출력. 생각은 화면 문장 검증(별칭 슬롯)을 거친다."""
    thought: str
    action: CourseDirectCall

"""모델과 주고받는 구조(명세 7·11절). 모델 출력은 이 스키마로 검증한 뒤에만 실행한다.

매개변수는 전부 별칭(p1, d1, t1)이다. 좌표, 날짜, 장소 id는 모델이 만들 수 없다(명세 3절 2번).
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from agent.course.constants import PLAN_MAX_STEPS


class _Strict(BaseModel):
    # 모르는 필드가 오면 실패시킨다 — 모델이 스키마 밖의 값을 끼워 넣어도 조용히 버리지 않는다.
    model_config = ConfigDict(extra="forbid")


# ---- 수리 ----

class Swap(_Strict):
    """두 장소의 자리를 바꾼다. 같은 날 안이든 다른 날 사이든 된다."""
    type: Literal["swap"]
    a: str
    b: str


class MoveDay(_Strict):
    """장소를 다른 날로 옮긴다(이월). position이 없으면 코드가 그날 이동이 가장 짧은 자리에 넣는다."""
    type: Literal["move_day"]
    place: str
    to_day: str
    position: Optional[int] = None


class ReorderDay(_Strict):
    """그날의 장소 순서를 통째로 정한다. 그날 장소의 완전한 순열이어야 한다."""
    type: Literal["reorder_day"]
    day: str
    places: list[str]


Move = Annotated[Union[Swap, MoveDay, ReorderDay], Field(discriminator="type")]


# ---- 도구 호출 ----

class GetOpeningHours(_Strict):
    tool: Literal["get_opening_hours"]
    place: str


class FindOpenDays(_Strict):
    tool: Literal["find_open_days"]
    place: str


class EstimateTravel(_Strict):
    tool: Literal["estimate_travel"]
    from_place: str
    to_place: str


class TryMove(_Strict):
    tool: Literal["try_move"]
    move: Move


class CommitMove(_Strict):
    tool: Literal["commit_move"]
    trial_id: str


class Revert(_Strict):
    tool: Literal["revert"]
    to_step: int


class Finish(_Strict):
    tool: Literal["finish"]
    reason_code: Literal["solved", "no_progress", "budget"]


ToolCall = Annotated[
    Union[GetOpeningHours, FindOpenDays, EstimateTravel, TryMove, CommitMove, Revert, Finish],
    Field(discriminator="tool"),
]


# ---- 턴 출력 ----

class PlanStep(_Strict):
    step: int
    intent: str


class AgentTurn(_Strict):
    """모델 호출 한 번의 출력. 생각·계획·교훈은 상태를 바꾸지 않는다 — 상태는 action(도구)으로만 바뀐다."""
    thought: str
    plan: list[PlanStep] = Field(default_factory=list, max_length=PLAN_MAX_STEPS)
    lesson: Optional[str] = None
    action: ToolCall

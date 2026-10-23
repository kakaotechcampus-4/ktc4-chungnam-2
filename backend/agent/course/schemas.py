"""모델과 주고받는 구조(명세 7·11절). 정본은 `llm.schemas`의 Course* — 모델 출력 스키마는 llm이 갖고, 여기서는 짧은
이름으로 다시 내보낸다(다른 모듈의 schemas.py import는 허용, backend/CLAUDE.md).

매개변수는 전부 별칭(p1, d1, t1)이다. 좌표, 날짜, 장소 id는 모델이 만들 수 없다(명세 3절 2번).
"""

from llm.schemas import (
    CourseCommitMove as CommitMove,
    CourseEstimateTravel as EstimateTravel,
    CourseFindOpenDays as FindOpenDays,
    CourseFinish as Finish,
    CourseGetOpeningHours as GetOpeningHours,
    CourseMove as Move,
    CourseMoveDay as MoveDay,
    CoursePlanStep as PlanStep,
    CourseReorderDay as ReorderDay,
    CourseRevert as Revert,
    CourseSwap as Swap,
    CourseToolCall as ToolCall,
    CourseTryMove as TryMove,
    CourseTurn as AgentTurn,
)

__all__ = [
    "AgentTurn", "CommitMove", "EstimateTravel", "FindOpenDays", "Finish", "GetOpeningHours", "Move", "MoveDay",
    "PlanStep", "ReorderDay", "Revert", "Swap", "ToolCall", "TryMove",
]

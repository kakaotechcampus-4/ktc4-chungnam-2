"""llm 모듈이 다른 모듈에 여는 공개 함수 — 다른 모듈은 service.py 대신 여기서만 가져간다(docs/architecture.md 1절).

지금 쓰는 곳은 recommend뿐이고 ②(사유 구조화)만 연다. ③-a-1·③-b는 v1 요청 중에 부르지 않는다.
dev/real을 고르는 일은 이 모듈이 아니라 받는 쪽의 Gateway(recommend/deps.py)가 한다.
"""

from llm.schemas import EvidenceLine
from llm.service import (
    EvidencePlanner,
    PlanEvidenceFailed,
    passthrough_planner,
    plan_evidence,
    real_evidence_planner,
)

__all__ = [
    "EvidenceLine", "EvidencePlanner", "PlanEvidenceFailed",
    "passthrough_planner", "plan_evidence", "real_evidence_planner",
]

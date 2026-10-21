"""AI 코스 짜기 API의 요청·응답(docs/api-spec.yaml `course` 태그와 1:1, #334 — 팀 결정 #580 전 브랜치 초안).

엔진 쪽 구조(`schemas.py`, 모델과 주고받는 별칭 구조)와 따로 둔다. 여기는 화면과 주고받는 값이다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agent.course.constants import MEMBER_WALK_MAX, MEMBER_WALK_MIN, REQUEST_TEXT_MAX_CHARS


class MemberConstraint(BaseModel):
    kind: Literal["daily_walk_max"]
    value: int = Field(ge=MEMBER_WALK_MIN, le=MEMBER_WALK_MAX, description="하루 도보 상한(분)")
    day: Optional[str] = Field(default=None, pattern=r"^d[1-9][0-9]*$", description="날짜 별칭 d1 … 없으면 모든 날")


class CourseRequest(BaseModel):
    request_text: Optional[str] = Field(default=None, max_length=REQUEST_TEXT_MAX_CHARS)
    member_constraints: list[MemberConstraint] = Field(default_factory=list, max_length=10)


class CourseRunCreated(BaseModel):
    course_run_id: str


class CourseGoal(BaseModel):
    id: str
    kind: str
    label: str
    met: Optional[bool] = None       # null = 판단할 수 없음(라벨을 아는 장소가 없다)


class CourseStep(BaseModel):
    stage: str                       # 이해 · 확인 · 짜기 · 점검 · 재계획 · 다시 짜기 · 고정 · 질문 · 답 · 대행 · 끝 · 결과
    by: str                          # 누가 했는지 한국어 그대로: 모델, 코드, 사람, "모델 → 코드" 같은 조합
    text: str


class CourseSlot(BaseModel):
    pin_id: str
    order: int
    needs_check: bool                # 그날 영업하는지 모른다 — 가게에 확인


class CourseLeg(BaseModel):
    from_pin_id: str
    to_pin_id: str
    approx_minutes: int


class CourseDay(BaseModel):
    date: date
    slots: list[CourseSlot]
    legs: list[CourseLeg]


class CourseViolation(BaseModel):
    kind: Literal["closed", "travel", "member"]
    text: str


class CourseCheck(BaseModel):
    pin_id: str
    text: str


class CourseExcluded(BaseModel):
    pin_id: str
    reason: str                      # NO_COORDINATES | OVER_LIMIT
    text: str


class CourseRun(BaseModel):
    id: str
    map_id: str
    status: Literal["queued", "running", "done", "failed"]
    outcome: Optional[Literal["solved", "solved_with_checks", "unresolved", "timeout"]] = None
    failure_code: Optional[Literal["INTERRUPTED", "ENGINE_ERROR"]] = None
    goals: list[CourseGoal]
    unmatched: list[str]
    steps: list[CourseStep]
    days: list[CourseDay]
    violations: list[CourseViolation]
    checks: list[CourseCheck]
    excluded: list[CourseExcluded]
    snapshot_at: datetime
    stale: bool                      # 요청 뒤 확정 리스트가 바뀌었다 — 「다시 짜기」
    created_at: datetime
    finished_at: Optional[datetime] = None

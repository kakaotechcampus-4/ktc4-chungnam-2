"""동선 에이전트(AI 코스 짜기)가 소유하는 테이블 1개 — `agent_course_runs`(마이그레이션 0037, #334, 팀 결정 #580 전 브랜치 초안).

- `map_id`, `requested_by`는 다른 모듈처럼 문자열이고 FK가 없다(agent 테이블과 같은 관례).
- run은 요청자 본인 것이다(가드레일 1). 다른 구성원에게 보이지 않는다.
- 사유 원문은 저장하지 않는다. 요청 한 줄(`input.request_text`)은 요청자가 이 run을 위해 직접 쓴 글이다. 장소 이름과 좌표도 저장하지
  않는다 — 핀은 `pin_id`로만 가리키고, 화면 문장(steps·violations·checks)에 들어간 이름은 코드가 렌더한 문장 안에만 있다.
- 지도 삭제 정리와 탈퇴 정리는 `course.api`(purge_map_data, delete_by_user)가 한다. 연결은 #580 결정 뒤다.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

COURSE_STATUSES = ("queued", "running", "done", "failed")
ACTIVE_STATUSES = ("queued", "running")
COURSE_OUTCOMES = ("solved", "solved_with_checks", "unresolved", "timeout")
FAILURE_CODES = ("INTERRUPTED", "ENGINE_ERROR")   # failed일 때만. 예외 클래스 이름 같은 것은 로그에만 남긴다

_EMPTY_LIST = text("'[]'::jsonb")


class AgentCourseRun(Base):
    __tablename__ = "agent_course_runs"
    __table_args__ = (
        Index("ix_agent_course_runs_map_user", "map_id", "requested_by", "created_at"),
        Index("ix_agent_course_runs_user_created", "requested_by", "created_at"),   # 하루 상한을 센다
        # 내 진행 중 run은 지도당 하나(COURSE_IN_PROGRESS). 동시 요청이 확인을 함께 통과해도 DB가 막는다
        Index(
            "uq_agent_course_runs_active", "map_id", "requested_by", unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)   # COURSE_STATUSES
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)   # COURSE_OUTCOMES. done일 때만
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)   # FAILURE_CODES. failed일 때만
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)   # {request_text, member_constraints:[{kind, value, day}]}
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_pin_ids: Mapped[list] = mapped_column(JSONB, nullable=False)   # 요청 때 확정 리스트의 핀. 바뀌었는지(stale) 비교용
    goals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{id, kind, label, met}]
    unmatched: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # 요청 원문 조각
    excluded: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{pin_id, reason, text}]
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{stage, by, text}]
    days: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{date, slots, legs}]
    violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{kind, text}]
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)   # [{pin_id, text}]
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")   # 지휘 모델 턴 수
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

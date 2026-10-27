"""authz.guard.require_with_principal()이 쓸 코스 run 로더(agent/loaders.py, recommend/loaders.py와 같은 패턴).

run id로 읽은 행의 지도와 요청자로 Resource(type="run", author_id=requested_by)를 만든다 — 그 뒤 authz.guard가 비구성원 404,
요청자가 아니면 403을 판정한다(가드레일 1: 코스는 요청한 사람에게만 보인다).
"""

from dataclasses import dataclass

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from agent.course import service
from agent.course.models import AgentCourseRun
from authz.core import Resource
from common.database import get_db_session
from common.errors import AppError


@dataclass(frozen=True)
class LoadedCourseRun:
    resource: Resource
    obj: AgentCourseRun


def load_course_run(runId: str = Path(...), db: Session = Depends(get_db_session)) -> LoadedCourseRun:
    row = service.get_run(db, runId)
    if row is None:
        raise AppError("NOT_FOUND")
    return LoadedCourseRun(resource=Resource(type="run", map_id=row.map_id, author_id=row.requested_by), obj=row)

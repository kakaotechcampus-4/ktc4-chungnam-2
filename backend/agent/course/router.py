"""docs/api-spec.yaml `course` 태그 — 「AI 코스 짜기」(#334, 팀 결정 #580 전 브랜치 초안).

인가는 여기서 분기하지 않는다(authz.guard, docs/permissions.md).
- POST /maps/{mapId}/courses: require_on_map("course.request") — 구성원 누구나
- GET /course-runs/{runId}: require_with_principal("course.view", load_course_run) — 요청자 본인만(비구성원 404, 요청자 아님 403)
- GET /maps/{mapId}/courses/latest: require_map_member() — 조회는 멤버십만, 내 run만 본다

POST는 run을 queued로 저장해 커밋한 뒤 202를 돌려주고, 계산은 BackgroundTasks가 한다(service.execute_run). 질문에 답하는 API는 없다.
"""

from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Response
from sqlalchemy.orm import Session

from agent.course import service
from agent.course.api_schemas import CourseRequest, CourseRun, CourseRunCreated
from agent.course.gateways import LlmDep, OpeningHoursDep, SessionFactoryDep
from agent.course.loaders import load_course_run
from auth.deps import get_current_user
from authz.core import Principal
from authz.guard import require_map_member, require_on_map, require_with_principal
from common.database import get_db_session

router = APIRouter(tags=["course"], dependencies=[Depends(get_current_user)])

CourseToRequest = Depends(require_on_map("course.request"))
CourseToView = Depends(require_with_principal("course.view", load_course_run))
CourseForMap = Depends(require_map_member())
DbSession = Depends(get_db_session)


@router.post("/maps/{mapId}/courses", response_model=CourseRunCreated, status_code=202)
def post_course(
    background: BackgroundTasks, body: CourseRequest | None = None, mapId: str = Path(...),
    principal: Principal = CourseToRequest, db: Session = DbSession, llm=LlmDep, gateway=OpeningHoursDep,
    session_factory: Callable[[], Session] = SessionFactoryDep,
):
    body = body or CourseRequest()
    job = service.request_course(
        db, map_id=mapId, requested_by=principal.user_id, body=body, now=datetime.now(timezone.utc),
    )
    db.commit()   # 백그라운드가 이 행을 읽는다 — 응답과 백그라운드가 시작되기 전에 저장을 끝낸다
    background.add_task(service.execute_run, job, session_factory=session_factory, llm=llm, gateway=gateway)
    return CourseRunCreated(course_run_id=job.run_id)


@router.get("/maps/{mapId}/courses/latest", response_model=CourseRun, responses={204: {"description": "아직 짠 코스가 없음"}})
def get_latest_course(mapId: str = Path(...), principal: Principal = CourseForMap, db: Session = DbSession):
    service.fail_stale_runs(db, map_id=mapId, requested_by=principal.user_id, now=datetime.now(timezone.utc))
    db.commit()   # 오래된 진행 중 run을 끝낸 뒤에 읽는다 — 끝났는지는 서버가 정한다(#736)
    row = service.latest_run(db, map_id=mapId, requested_by=principal.user_id)
    if row is None:
        return Response(status_code=204)
    return service.to_response(db, row)


@router.get("/course-runs/{runId}", response_model=CourseRun)
def get_course_run(loaded=CourseToView, db: Session = DbSession):
    row, _principal = loaded
    service.fail_stale_runs(db, run_id=row.id, now=datetime.now(timezone.utc))
    db.commit()   # 커밋이 행을 만료시켜 아래 응답이 바뀐 값을 읽는다(#736)
    return service.to_response(db, row)

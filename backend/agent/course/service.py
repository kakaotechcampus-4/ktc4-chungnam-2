"""AI 코스 짜기 run의 읽기·쓰기와 실행(명령형 셸, #334 — 팀 결정 #580 전 브랜치 초안). 엔진(core·direct·runner)은 순수라 DB를 모른다.

다른 모듈 데이터는 `<module>/api.py`로만 읽는다(#113): 지도 기간(`maps.api`), 확정 항목(`shortlist.api`), 핀(`pins.api`),
장소 이름·좌표·라벨(`places.api`).

실행 순서는 읽기 → 롤백 → 모델 → 쓰기다(backend/CLAUDE.md "모델 호출과 트랜잭션"). 요청(`request_course`)이 지도를 읽어 run을
`queued`로 저장하고, 백그라운드(`execute_run`)가 짧은 세션 두 개로 running 표시와 결과 저장을 한다. 모델을 부르는 동안 세션을
잡지 않는다. 읽은 장소 정보(이름·좌표)는 메모리의 `CourseJob`에만 있고 DB에 남지 않는다.

질문에는 답을 받지 않는다(엔진이 답이 없으면 기본값으로 이어 간다). 그래서 waiting_input 상태도 답 API도 없다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.course import runner, worklog
from agent.course.api_schemas import CourseRequest, CourseRun
from agent.course.constants import (
    COURSE_DAILY_LIMIT, COURSE_DAY_BOUNDARY_TZ, COURSE_DAYS_MAX, EXCLUDED_OVER_LIMIT, EXCLUDED_OVER_LIMIT_MESSAGE,
    MAX_PLACES, MIN_PLACES,
)
from agent.course.core import MemberConstraint
from agent.course.gateways import CourseLlm
from agent.course.intake import Excluded, PinInput, TripBuild, build_trip
from agent.course.models import ACTIVE_STATUSES, AgentCourseRun
from agent.course.ports import OpeningHoursGateway
from common.errors import AppError
from maps import api as maps_api
from pins import api as pins_api
from places import api as places_api
from shortlist import api as shortlist_api

log = logging.getLogger("pingo.agent.course")

# 진행 중으로 남은 run이 이 시간을 넘기면 죽은 것으로 보고 끝낸다 — 서버 재시작이 정리해 주지 못한 경우(여러 인스턴스 등)에도
# 사용자가 영영 COURSE_IN_PROGRESS에 막히지 않게 한다. 모델 호출 상한(약 1분)보다 충분히 길다
STALE_AFTER = timedelta(minutes=15)


# ---------------------------------------------------------------- 지도 읽기

@dataclass(frozen=True)
class Snapshot:
    start_date: date
    end_date: date
    confirmed_pin_ids: tuple[str, ...]      # 확정 항목의 핀 전부(확정 순서). 바뀌었는지(stale) 비교에 쓴다
    pins: tuple[PinInput, ...]              # 그중 공개이고 지워지지 않은 핀


def read_snapshot(db: Session, map_id: str) -> Optional[Snapshot]:
    """지도 기간과 확정 리스트의 핀을 읽는다. 지도가 없거나 삭제됐으면 None. 읽기 전용, 커밋하지 않는다.

    좌표가 있는 핀은 자체 DB 장소(db 핀)뿐이다. 실시간 핀(#382)은 place_id가 없어 PinInput의 좌표가 None이 되고 동선에서 빠진다.
    카카오 응답은 읽지도 저장하지도 않는다(#53)."""
    found = maps_api.get_map_for_agent(db, map_id)
    if found is None or found["deleted"]:
        return None
    items = shortlist_api.list_items_for_agent(db, map_id=map_id)
    matrix = {p["pin_id"]: p for p in pins_api.list_reaction_matrix(db, map_id=map_id)}
    confirmed = [matrix[i["pin_id"]] for i in items if i["pin_id"] in matrix]
    place_ids = [p["place_id"] for p in confirmed if p["place_id"]]
    infos = places_api.get_places(place_ids, db=db) if place_ids else {}
    facts = places_api.get_facts(place_ids, db=db) if place_ids else {}
    pins = []
    for p in confirmed:
        info = infos.get(p["place_id"]) if p["place_id"] else None
        if info is None:     # 실시간 핀, 또는 장소가 정리돼 없는 핀
            pins.append(PinInput(p["pin_id"], None, p["search_query"] or "", p["category"]))
            continue
        labels = frozenset(f.fact_key for f in facts.get(p["place_id"], ()) if f.confidence == "known" and f.value is True)
        pins.append(PinInput(p["pin_id"], p["place_id"], info.name, p["category"], info.lat, info.lng, labels))
    return Snapshot(found["start_date"], found["end_date"], tuple(i["pin_id"] for i in items), tuple(pins))


def current_confirmed_pin_ids(db: Session, map_id: str) -> set[str]:
    return {i["pin_id"] for i in shortlist_api.list_items_for_agent(db, map_id=map_id)}


# ---------------------------------------------------------------- 입력 만들기 (순수)

def trip_days(start: date, end: date) -> list[date]:
    n = min((end - start).days + 1, COURSE_DAYS_MAX)
    return [start + timedelta(days=i) for i in range(n)]


def member_constraints(body: CourseRequest, n_days: int) -> tuple[MemberConstraint, ...]:
    """요청의 구성원 제약을 엔진 값으로. 날짜 별칭이 여행 기간 밖이면 422."""
    out = []
    for c in body.member_constraints:
        if c.day is not None and not 1 <= int(c.day[1:]) <= n_days:
            raise AppError("VALIDATION_ERROR", "member_constraints.day가 여행 기간 밖입니다", detail={"day": c.day})
        out.append(MemberConstraint(c.kind, c.value, c.day))
    return tuple(out)


def build_input(snapshot: Snapshot, body: CourseRequest) -> TripBuild:
    """MAX_PLACES를 넘는 핀은 확정 순서대로 앞에서 자르고 나머지는 "빠졌어요"로 보인다. 좌표 없는 핀은 intake가 뺀다."""
    days = trip_days(snapshot.start_date, snapshot.end_date)
    routable = [p for p in snapshot.pins if p.routable]
    kept = {p.pin_id for p in routable[:MAX_PLACES]}
    pins = [p for p in snapshot.pins if not p.routable or p.pin_id in kept]
    built = build_trip(pins, days, member_constraints(body, len(days)), unknown_hours="check")
    over = tuple(Excluded(p.pin_id, p.name, EXCLUDED_OVER_LIMIT, EXCLUDED_OVER_LIMIT_MESSAGE) for p in routable[MAX_PLACES:])
    return TripBuild(built.trip, built.excluded + over)


def kst_day_start(now: datetime) -> datetime:
    """now가 속한 KST 날짜의 자정(UTC aware). 하루 상한은 이 시각부터 센다."""
    tz = ZoneInfo(COURSE_DAY_BOUNDARY_TZ)
    local = now.astimezone(tz)
    return datetime(local.year, local.month, local.day, tzinfo=tz).astimezone(timezone.utc)


# ---------------------------------------------------------------- 요청

@dataclass(frozen=True)
class CourseJob:
    """백그라운드가 실행할 일. 장소 이름과 좌표를 담고 있어 메모리에서만 쓰고 저장하지 않는다."""
    run_id: str
    build: TripBuild
    request_text: str


def fail_stale_runs(db: Session, *, map_id: str, requested_by: str, now: datetime) -> int:
    """STALE_AFTER를 넘겨 진행 중으로 남은 내 run을 INTERRUPTED로 끝낸다."""
    res = db.execute(
        update(AgentCourseRun)
        .where(AgentCourseRun.map_id == map_id, AgentCourseRun.requested_by == requested_by,
               AgentCourseRun.status.in_(ACTIVE_STATUSES), AgentCourseRun.created_at < now - STALE_AFTER)
        .values(status="failed", failure_code="INTERRUPTED", finished_at=now)
    )
    return res.rowcount


def _active_run(db: Session, map_id: str, requested_by: str) -> Optional[AgentCourseRun]:
    return db.execute(
        select(AgentCourseRun).where(
            AgentCourseRun.map_id == map_id, AgentCourseRun.requested_by == requested_by,
            AgentCourseRun.status.in_(ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()


def count_since(db: Session, *, requested_by: str, since: datetime) -> int:
    return db.execute(
        select(func.count()).select_from(AgentCourseRun)
        .where(AgentCourseRun.requested_by == requested_by, AgentCourseRun.created_at >= since)
    ).scalar_one()


def request_course(db: Session, *, map_id: str, requested_by: str, body: CourseRequest, now: datetime) -> CourseJob:
    """검증하고 run을 queued로 저장한다(커밋은 호출부). 422 → 409 → 429 순서로 확인한다.

    확정 장소 부족 422 `COURSE_NOT_ENOUGH_PLACES`, 내 진행 중 run이 있으면 409 `COURSE_IN_PROGRESS`, 오늘 5번을 넘기면
    429 `COURSE_LIMIT`. 지도가 없거나 삭제됐으면 404."""
    snapshot = read_snapshot(db, map_id)
    if snapshot is None:
        raise AppError("NOT_FOUND")
    build = build_input(snapshot, body)
    if build.too_few:
        count = sum(p.routable for p in snapshot.pins)
        raise AppError("COURSE_NOT_ENOUGH_PLACES", detail={"min": MIN_PLACES, "count": count})
    fail_stale_runs(db, map_id=map_id, requested_by=requested_by, now=now)
    active = _active_run(db, map_id, requested_by)
    if active is not None:
        raise AppError("COURSE_IN_PROGRESS", detail={"course_run_id": str(active.id)})
    used = count_since(db, requested_by=requested_by, since=kst_day_start(now))
    if used >= COURSE_DAILY_LIMIT:
        raise AppError("COURSE_LIMIT", detail={"limit": COURSE_DAILY_LIMIT, "used": used})
    text = (body.request_text or "").strip()
    row = AgentCourseRun(
        id=uuid.uuid4(), map_id=map_id, requested_by=requested_by, status="queued", created_at=now, snapshot_at=now,
        snapshot_pin_ids=list(snapshot.confirmed_pin_ids),
        input={"request_text": text, "member_constraints": [c.model_dump() for c in body.member_constraints]},
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:      # 동시 요청이 확인을 함께 통과했다 — 부분 유니크 인덱스가 하나만 남긴다
        raise AppError("COURSE_IN_PROGRESS") from None
    return CourseJob(str(row.id), build, text)


# ---------------------------------------------------------------- 실행 (백그라운드)

def execute_run(
    job: CourseJob, *, session_factory: Callable[[], Session], llm: CourseLlm, gateway: OpeningHoursGateway,
) -> None:
    """queued run을 돌려 결과를 저장한다. 예외를 밖으로 던지지 않는다(백그라운드라 받을 곳이 없다).

    세션은 짧게 여러 번이다: ① running 표시, ② 단계가 생길 때마다 steps 저장(progress_writer), ③ 결과 저장. 사이에서 모델을
    부른다 — 그동안 연결을 잡지 않는다."""
    run_id = uuid.UUID(job.run_id)
    try:
        with session_factory() as db:
            started = db.execute(
                update(AgentCourseRun).where(AgentCourseRun.id == run_id, AgentCourseRun.status == "queued")
                .values(status="running")
            ).rowcount
            db.commit()
        if not started:      # 그 사이 지워졌거나 INTERRUPTED로 끝났다
            return
        try:
            computed = runner.run_course(
                job.build, job.request_text,
                goals_planner=llm.goals_planner, direct_planner=llm.direct_planner, gateway=gateway,
                on_step=progress_writer(session_factory, run_id),
            )
            values = _done_values(computed)
        except Exception as exc:   # noqa: BLE001 — 엔진 오류가 run을 running으로 남기면 안 된다. 클래스 이름만 로그(사유·요청 원문 금지)
            log.warning("course run %s 실패: %s", job.run_id, type(exc).__name__)
            values = {"status": "failed", "failure_code": "ENGINE_ERROR"}
        with session_factory() as db:
            db.execute(
                update(AgentCourseRun).where(AgentCourseRun.id == run_id, AgentCourseRun.status == "running")
                .values(finished_at=datetime.now(timezone.utc), **values)
            )
            db.commit()
    except Exception as exc:   # noqa: BLE001 — DB 오류 등. 남은 running은 STALE_AFTER 뒤 다음 요청이 정리한다
        log.warning("course run %s 저장 실패: %s", job.run_id, type(exc).__name__)


def progress_writer(session_factory: Callable[[], Session], run_id: uuid.UUID) -> Callable[[worklog.StepRecord], None]:
    """단계가 생길 때마다 steps를 저장하는 콜백. 세션은 호출마다 따로 열고 커밋하고 닫는다(모델 호출 중에 잡고 있지 않는다).
    매번 지금까지의 전체 목록을 쓴다 — 한 번 빠져도 다음 저장이 메우고, 순서가 뒤집히지 않는다. running일 때만 쓴다(그 사이
    지워지거나 INTERRUPTED로 끝난 run은 건드리지 않는다)."""
    steps: list[dict] = []

    def write(record: worklog.StepRecord) -> None:
        steps.append(record.as_dict())
        with session_factory() as db:
            db.execute(
                update(AgentCourseRun).where(AgentCourseRun.id == run_id, AgentCourseRun.status == "running")
                .values(steps=list(steps))
            )
            db.commit()

    return write


def _done_values(c: runner.Computation) -> dict:
    v = c.view
    return {
        "status": "done", "outcome": v.outcome, "goals": v.goals, "unmatched": v.unmatched, "steps": v.steps,
        "days": v.days, "violations": v.violations, "checks": v.checks, "excluded": v.excluded,
        "model": c.model, "prompt_version": c.prompt_version, "model_turns": c.model_turns,
        "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
    }


def interrupt_unfinished_runs(session_factory: Callable[[], Session], *, now: Optional[datetime] = None) -> int:
    """서버 시작 때 부른다 — 진행 중(queued·running)으로 남은 run을 INTERRUPTED로 끝낸다(백그라운드 작업은 프로세스와 함께 사라졌다).
    인스턴스가 하나라는 전제다(여러 개로 늘리면 Cloud Tasks로 옮긴다, #168). 끝낸 수를 돌려준다."""
    with session_factory() as db:
        n = db.execute(
            update(AgentCourseRun).where(AgentCourseRun.status.in_(ACTIVE_STATUSES))
            .values(status="failed", failure_code="INTERRUPTED", finished_at=now or datetime.now(timezone.utc))
        ).rowcount
        db.commit()
    return n


# ---------------------------------------------------------------- 읽기

def get_run(db: Session, run_id: str) -> Optional[AgentCourseRun]:
    try:
        key = uuid.UUID(run_id)
    except ValueError:
        return None
    return db.get(AgentCourseRun, key)


def latest_run(db: Session, *, map_id: str, requested_by: str) -> Optional[AgentCourseRun]:
    return db.execute(
        select(AgentCourseRun).where(AgentCourseRun.map_id == map_id, AgentCourseRun.requested_by == requested_by)
        .order_by(AgentCourseRun.created_at.desc(), AgentCourseRun.id.desc()).limit(1)
    ).scalar_one_or_none()


def _with_leg_modes(days: list) -> list:
    """mode가 생기기 전(#685)에 저장된 run은 구간에 mode가 없다 — 그때는 모든 구간이 도보였으니 walk로 읽는다."""
    return [{**d, "legs": [{"mode": "walk", **leg} for leg in d.get("legs", [])]} for d in days or []]


def to_response(db: Session, row: AgentCourseRun) -> CourseRun:
    stale = set(row.snapshot_pin_ids) != current_confirmed_pin_ids(db, row.map_id)
    return CourseRun.model_validate({
        "id": str(row.id), "map_id": row.map_id, "status": row.status, "outcome": row.outcome,
        "failure_code": row.failure_code, "goals": row.goals, "unmatched": row.unmatched, "steps": row.steps,
        "days": _with_leg_modes(row.days), "violations": row.violations, "checks": row.checks, "excluded": row.excluded,
        "snapshot_at": row.snapshot_at, "stale": stale, "created_at": row.created_at, "finished_at": row.finished_at,
    })


# ---------------------------------------------------------------- 정리 (연결은 #580 결정 뒤)

def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    if not map_ids:
        return {"agent_course_runs": 0}
    return {"agent_course_runs": db.execute(delete(AgentCourseRun).where(AgentCourseRun.map_id.in_(map_ids))).rowcount}


def delete_by_user(db: Session, *, user_id: str) -> dict[str, int]:
    """탈퇴 — 그 사람이 요청한 run을 모두 지운다(요청 한 줄과 결과는 요청자 본인 것이다)."""
    return {"agent_course_runs": db.execute(delete(AgentCourseRun).where(AgentCourseRun.requested_by == user_id)).rowcount}

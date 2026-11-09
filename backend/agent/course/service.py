"""AI 코스 짜기 run의 읽기·쓰기와 실행(명령형 셸, #334 — 팀 결정 #580 전 브랜치 초안). 엔진(core·direct·runner)은 순수라 DB를 모른다.

다른 모듈 데이터는 `<module>/api.py`로만 읽는다(#113): 지도 기간(`maps.api`), 확정 항목(`shortlist.api`), 핀(`pins.api`),
장소 이름·좌표·라벨(`places.api`).

실행 순서는 읽기 → 롤백 → 모델 → 쓰기다(backend/CLAUDE.md "모델 호출과 트랜잭션"). 요청(`request_course`)이 지도를 읽어 run을
`queued`로 저장하고, 백그라운드(`execute_run`)가 짧은 세션 두 개로 running 표시와 결과 저장을 한다. 모델을 부르는 동안 세션을
잡지 않는다. 읽은 장소 정보(이름·좌표)는 메모리의 `CourseJob`에만 있고 DB에 남지 않는다.

질문에는 답을 받지 않는다(엔진이 답이 없으면 기본값으로 이어 간다). 그래서 waiting_input 상태도 답 API도 없다.

크레딧(#432, docs/credits-reviews.md 3.3): 요청이 run을 저장하는 트랜잭션에서 `credits.api.charge`로 가격만큼 뺀다. 모델은 접수 뒤
백그라운드에서 부르므로 이 차감이 잔액 확인을 겸한다(모자라면 402, 게스트 403 — run도 남지 않는다). 결과 없이 끝난 run
(`ENGINE_ERROR`, `INTERRUPTED`)은 끝내는 트랜잭션에서 `credits.api.refund`로 돌려준다. 가격 숫자는 credits가 든다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent import service as agent_service
from agent.course import goals as goals_mod, runner, worklog
from agent.course.api_schemas import CourseRequest, CourseRun
from agent.course.constants import (
    COURSE_DAYS_MAX, EXCLUDED_OVER_LIMIT, EXCLUDED_OVER_LIMIT_MESSAGE, MAP_SUMMARY_SECTIONS, MAX_PLACES, MIN_PLACES, STALE_AFTER,
)
from agent.course.core import MemberConstraint
from agent.course.gateways import CourseLlm
from agent.course.intake import Excluded, PinInput, TripBuild, build_trip
from agent.course.models import ACTIVE_STATUSES, AgentCourseRun
from agent.course.ports import OpeningHoursGateway
from common.errors import AppError
from credits import api as credits_api
from llm import api as llm_api
from maps import api as maps_api
from pins import api as pins_api
from places import api as places_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api

log = logging.getLogger("pingo.agent.course")

CREDIT_FEATURE = "course"      # credits 가격표의 키(= llm_calls.feature 라벨). 가격은 credits/constants.py에서 찾는다


# ---------------------------------------------------------------- 지도 읽기

@dataclass(frozen=True)
class Snapshot:
    start_date: date
    end_date: date
    version: str                            # 일정 version(shortlist) — 장소 집합·날짜 배정·순서·여행 기간. 바뀌었는지(stale) 비교에 쓴다
    pins: tuple[PinInput, ...]              # 그중 공개이고 지워지지 않은 핀(scheduled_date는 사람이 일정에 넣은 날, #1237)


def read_snapshot(db: Session, map_id: str) -> Optional[Snapshot]:
    """지도 기간과 확정 리스트의 핀을 읽는다. 지도가 없거나 삭제됐으면 None. 읽기 전용, 커밋하지 않는다.

    좌표가 있는 핀은 자체 DB 장소(db 핀)뿐이다. 실시간 핀(#382)은 place_id가 없어 PinInput의 좌표가 None이 되고 동선에서 빠진다.
    카카오 응답은 읽지도 저장하지도 않는다(#53)."""
    found = maps_api.get_map_for_agent(db, map_id)
    if found is None or found["deleted"]:
        return None
    schedule = shortlist_api.get_schedule_for_agent(db, map_id=map_id)
    items = sorted(schedule["items"], key=lambda i: i["added_at"])      # 일정은 날짜 순으로 오므로 확정 순서(별칭·MAX_PLACES 기준)로 되돌린다
    when = {i["pin_id"]: i["scheduled_date"] for i in items}
    order = {i["pin_id"]: i["visit_order"] for i in items}
    matrix = {p["pin_id"]: p for p in pins_api.list_reaction_matrix(db, map_id=map_id)}
    confirmed = [matrix[i["pin_id"]] for i in items if i["pin_id"] in matrix]
    return Snapshot(found["start_date"], found["end_date"], schedule["version"], _pin_inputs(db, confirmed, when, order))


def read_pins(db: Session, map_id: str, pin_ids: list[str]) -> tuple[PinInput, ...]:
    """이 지도의 핀(확정하지 않은 핀도)을 일정에 넣지 않은 PinInput으로 — 「핑고 AI 조언」이 확정 일정에 끼워 볼 때 쓴다(agent-v2 6.10,
    #1356). 공개이고 지워지지 않은 핀만, pin_ids 순서로. 좌표 규칙은 read_snapshot과 같다(실시간 핀은 좌표 없음). 읽기 전용."""
    matrix = {p["pin_id"]: p for p in pins_api.list_reaction_matrix(db, map_id=map_id)}
    return _pin_inputs(db, [matrix[i] for i in pin_ids if i in matrix], {}, {})


def _pin_inputs(db: Session, rows: list[dict], when: dict, order: dict) -> tuple[PinInput, ...]:
    """핀 행(pins.api.list_reaction_matrix) → PinInput. 장소 이름·좌표·라벨은 places.api에서 한 번에 읽는다. when·order는 일정의 날짜와 순서."""
    place_ids = [p["place_id"] for p in rows if p["place_id"]]
    infos = places_api.get_places(place_ids, db=db) if place_ids else {}
    facts = places_api.get_facts(place_ids, db=db) if place_ids else {}
    pins = []
    for p in rows:
        info = infos.get(p["place_id"]) if p["place_id"] else None
        if info is None:     # 실시간 핀, 또는 장소가 정리돼 없는 핀
            pins.append(PinInput(p["pin_id"], None, p["search_query"] or "", p["category"], scheduled_date=when.get(p["pin_id"]), visit_order=order.get(p["pin_id"])))
            continue
        labels = frozenset(f.fact_key for f in facts.get(p["place_id"], ()) if f.confidence == "known" and f.value is True)
        pins.append(PinInput(p["pin_id"], p["place_id"], info.name, p["category"], info.lat, info.lng, labels, when.get(p["pin_id"]), order.get(p["pin_id"])))
    return tuple(pins)


def current_schedule_version(db: Session, map_id: str) -> Optional[str]:
    """지금 일정 version. 지도가 지워졌으면 None(어느 run의 version과도 다르다 → stale)."""
    try:
        return shortlist_api.get_schedule_for_agent(db, map_id=map_id)["version"]
    except AppError:
        return None


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
    return TripBuild(built.trip, built.excluded + over, built.locks, built.schedule, built.placed)


# ---------------------------------------------------------------- 요청

@dataclass(frozen=True)
class CourseJob:
    """백그라운드가 실행할 일. 장소 이름과 좌표를 담고 있어 메모리에서만 쓰고 저장하지 않는다."""
    run_id: str
    build: TripBuild
    request_text: str
    created_at: datetime   # run의 created_at — 실행 상한의 기준 시각이다(끊긴 run 판정과 같은 기준, #1609)
    map_id: str            # 사용량 기록(llm_calls, #870)의 라벨
    requested_by: str
    map_items: tuple[goals_mod.SummaryItem, ...] = ()     # 우리 조건 요약 줄(지도 목표 후보의 근거, #1131 B안)


def read_map_items(db: Session, map_id: str) -> tuple[goals_mod.SummaryItem, ...]:
    """우리 조건 요약(agent_reason_summaries)을 코스가 읽는 자리 — 여기 한 곳이다(#1131 B안). 같은 agent 모듈의 `service.list_summaries`를
    부르고, 요약에서 키·방향·사람 수만 꺼낸다(MAP_SUMMARY_SECTIONS 칸). 요약에는 사유 원문과 구성원이 없다(명세 2절 13번). 표시 이름은
    recommend.api.fact_labels(근거 줄·요약 화면과 같은 이름). 어느 키가 목표가 되는지는 goals.map_candidates가 MAP_GOAL_KEYS로 고른다."""
    labels = recommend_api.fact_labels()
    return tuple(
        goals_mod.SummaryItem(row.category, item["fact_key"], bool(item["wants"]), int(item["member_count"]),
                              labels.get(item["fact_key"], item["fact_key"]), must_keep=section == "must_keep")
        for row in agent_service.list_summaries(db, map_id)
        for section in MAP_SUMMARY_SECTIONS
        for item in (row.summary or {}).get(section, ())
        if item.get("wants") is not None
    )


def fail_stale_runs(
    db: Session, *, now: datetime, map_id: Optional[str] = None, requested_by: Optional[str] = None,
    run_id: Optional[uuid.UUID] = None,
) -> int:
    """시작(created_at) 뒤 STALE_AFTER(실행 상한 + 여유, constants)가 지나도록 진행 중으로 남은 run을 INTERRUPTED로 끝내고 그 run마다
    크레딧을 돌려준다. 살아 있는 run은 상한 안에 끝나므로 이 run은 어느 프로세스의 것이든 죽은 것이다(#1609). 끊긴 run 판정은 여기
    한 곳이다 — 요청(지도+사람), 조회(run id, 또는 지도+사람), 서버 시작(전체)이 범위만 달리해 부른다. 이미 끝난 run과 STALE_AFTER 안의
    run은 걸리지 않는다. 환불은 끝내기와 같은 트랜잭션이고 멱등이다(#950). 끝낸 수. 커밋은 호출부."""
    scope = [
        col == value for col, value in (
            (AgentCourseRun.map_id, map_id), (AgentCourseRun.requested_by, requested_by), (AgentCourseRun.id, run_id),
        ) if value is not None
    ]
    ended = db.execute(
        update(AgentCourseRun)
        .where(*scope, AgentCourseRun.status.in_(ACTIVE_STATUSES), AgentCourseRun.created_at < now - STALE_AFTER)
        .values(status="failed", failure_code="INTERRUPTED", finished_at=now)
        .returning(AgentCourseRun.id)
    ).scalars().all()
    for ended_id in ended:
        refund_credit(db, ended_id)
    return len(ended)


def refund_credit(db: Session, run_id: uuid.UUID) -> None:
    """결과 없이 끝난 run의 차감을 돌려준다. 멱등 — 이미 돌려줬거나 차감이 없던 run(#950 전 run)은 그대로 둔다. 커밋은 호출부."""
    credits_api.refund(db, feature=CREDIT_FEATURE, run_id=str(run_id))


def _active_run(db: Session, map_id: str, requested_by: str) -> Optional[AgentCourseRun]:
    return db.execute(
        select(AgentCourseRun).where(
            AgentCourseRun.map_id == map_id, AgentCourseRun.requested_by == requested_by,
            AgentCourseRun.status.in_(ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()


def request_course(db: Session, *, map_id: str, requested_by: str, body: CourseRequest, now: datetime) -> CourseJob:
    """검증하고 run을 queued로 저장하며 같은 트랜잭션에서 크레딧을 뺀다(커밋은 호출부). 422 → 409 → 403·402 순서로 확인한다.

    확정 장소 부족 422 `COURSE_NOT_ENOUGH_PLACES`, 내 진행 중 run이 있으면 409 `COURSE_IN_PROGRESS`, 게스트면 403
    `GUEST_NOT_ALLOWED`, 잔액이 모자라면 402 `CREDIT_INSUFFICIENT`(둘 다 credits.api.charge가 낸다 — 호출부가 롤백하므로 run도
    남지 않는다). 지도가 없거나 삭제됐으면 404."""
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
    text = (body.request_text or "").strip()
    row = AgentCourseRun(
        id=uuid.uuid4(), map_id=map_id, requested_by=requested_by, status="queued", created_at=now, snapshot_at=now,
        snapshot_version=snapshot.version, mode=build.mode,
        input={"request_text": text, "member_constraints": [c.model_dump() for c in body.member_constraints]},
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:      # 동시 요청이 확인을 함께 통과했다 — 부분 유니크 인덱스가 하나만 남긴다
        raise AppError("COURSE_IN_PROGRESS") from None
    credits_api.charge(db, user_id=requested_by, feature=CREDIT_FEATURE, run_id=str(row.id))
    return CourseJob(str(row.id), build, text, now, map_id=map_id, requested_by=requested_by, map_items=read_map_items(db, map_id))


# ---------------------------------------------------------------- 실행 (백그라운드)

def execute_run(
    job: CourseJob, *, session_factory: Callable[[], Session], llm: CourseLlm, gateway: OpeningHoursGateway,
) -> None:
    """queued run을 돌려 결과를 저장한다. 예외를 밖으로 던지지 않는다(백그라운드라 받을 곳이 없다). ENGINE_ERROR로 끝나면 크레딧을
    돌려준다. 저장까지 실패해 running으로 남은 run은 fail_stale_runs가 INTERRUPTED로 끝내며 돌려준다.

    세션은 짧게 여러 번이다: ① running 표시, ② 단계가 생길 때마다 steps 저장(progress_writer), ③ 결과 저장. 사이에서 모델을
    부른다 — 그동안 연결을 잡지 않는다. 실행 상한(constants.RUN_LIMIT)은 run의 created_at부터 센다(큐 대기 포함, #1609)."""
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
            with llm_api.usage_context("course", map_id=job.map_id, user_id=job.requested_by, run_id=job.run_id):
                computed = runner.run_course(
                    job.build, job.request_text, map_items=job.map_items,
                    goals_planner=llm.goals_planner, direct_planner=llm.direct_planner, gateway=gateway,
                    on_step=progress_writer(session_factory, run_id), started_at=job.created_at,
                )
            values = _done_values(computed)
        except Exception as exc:   # noqa: BLE001 — 엔진 오류가 run을 running으로 남기면 안 된다. 클래스 이름만 로그(사유·요청 원문 금지)
            log.warning("course run %s 실패: %s", job.run_id, type(exc).__name__)
            values = {"status": "failed", "failure_code": "ENGINE_ERROR"}
        with session_factory() as db:
            saved = db.execute(
                update(AgentCourseRun).where(AgentCourseRun.id == run_id, AgentCourseRun.status == "running")
                .values(finished_at=datetime.now(timezone.utc), **values)
            ).rowcount
            if saved and values["status"] == "failed":     # 결과 없이 끝났다 — 끝내기와 같은 트랜잭션에서 돌려준다
                refund_credit(db, run_id)
            db.commit()
    except Exception as exc:   # noqa: BLE001 — DB 오류 등. 남은 running은 STALE_AFTER 뒤 요청·조회가 정리한다
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
        "status": "done", "outcome": v.outcome, "headline": v.headline, "fixes": v.fixes, "checked": v.checked, "goals": v.goals, "unmatched": v.unmatched, "steps": v.steps,
        "days": v.days, "violations": v.violations, "checks": v.checks, "excluded": v.excluded,
        "model": c.model, "prompt_version": c.prompt_version, "model_turns": c.model_turns,
        "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
    }


def interrupt_unfinished_runs(session_factory: Callable[[], Session], *, now: Optional[datetime] = None) -> int:
    """서버 시작 때 부른다 — 죽은 프로세스가 남긴 진행 중(queued·running) run을 INTERRUPTED로 끝낸다. 판정과 환불은 요청·조회와 같은
    `fail_stale_runs`이고 범위만 전체다(#1609). STALE_AFTER 안의 run은 다른 프로세스에서 아직 도는 것일 수 있어 두고, 그 run이 끊긴
    것이었다면 STALE_AFTER 뒤 요청과 조회가 끝낸다. 끝낸 수를 돌려준다."""
    with session_factory() as db:
        n = fail_stale_runs(db, now=now or datetime.now(timezone.utc))
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
    stale = row.snapshot_version != current_schedule_version(db, row.map_id)
    return CourseRun.model_validate({
        "id": str(row.id), "map_id": row.map_id, "status": row.status, "mode": row.mode, "outcome": row.outcome,
        "failure_code": row.failure_code, "headline": row.headline, "goals": row.goals, "unmatched": row.unmatched, "steps": row.steps,
        "days": _with_leg_modes(row.days), "fixes": row.fixes, "checked": row.checked, "violations": row.violations, "checks": row.checks, "excluded": row.excluded,
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


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#694) — from_user가 요청한 run을 to_user 것으로 옮긴다. 커밋은 호출자.
    진행 중은 지도당 한 사람에 하나(uq_agent_course_runs_active)라서, 같은 지도에 둘 다 진행 중이면 from_user의 진행 중 run을
    지운다(to_user 쪽이 이긴다). 백그라운드 실행은 그 run이 지워졌으면 아무것도 쓰지 않는다(execute_run). 멱등, 같은 id면
    아무것도 안 한다."""
    if from_user_id == to_user_id:
        return {"agent_course_runs": 0, "agent_course_runs_dropped": 0}
    to_user_active_maps = select(AgentCourseRun.map_id).where(
        AgentCourseRun.requested_by == to_user_id, AgentCourseRun.status.in_(ACTIVE_STATUSES)
    )
    dropped = db.execute(
        delete(AgentCourseRun).where(
            AgentCourseRun.requested_by == from_user_id, AgentCourseRun.status.in_(ACTIVE_STATUSES),
            AgentCourseRun.map_id.in_(to_user_active_maps),
        )
    ).rowcount
    moved = db.execute(
        update(AgentCourseRun).where(AgentCourseRun.requested_by == from_user_id).values(requested_by=to_user_id)
    ).rowcount
    return {"agent_course_runs": moved, "agent_course_runs_dropped": dropped}

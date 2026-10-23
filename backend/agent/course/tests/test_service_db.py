"""AI 코스 짜기 서비스(service.py) — 실제 DB, 모델은 스텁이다. 요청 검증, 상한, 실행, 정리."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from agent.course import api as course_api, service
from agent.course.api_schemas import CourseRequest
from agent.course.constants import COURSE_DAILY_LIMIT, MAX_PLACES
from agent.course.gateways import CourseLlm, NullOpeningHours
from agent.course.models import AgentCourseRun
from agent.course.tests.conftest import confirmed_map
from agent.course.tests.test_runner import TEXT, direct_planner, goals_planner
from common.errors import AppError

NO_MODEL = CourseLlm(goals_planner=None, direct_planner=None)


def request(world, map_id, *, user="u1", body=None, now=None):
    with world.factory() as db:
        job = service.request_course(
            db, map_id=map_id, requested_by=world.uid(user), body=body or CourseRequest(), now=now or world.now,
        )
        db.commit()
        return job


def row(world, run_id):
    with world.factory() as db:
        return db.get(AgentCourseRun, uuid.UUID(run_id))


def code_of(excinfo) -> str:
    return excinfo.value.code


# ---------------------------------------------------------------- 요청

def test_request_saves_queued_run_with_snapshot_and_input(world, places):
    map_id, pin_ids = confirmed_map(world, places, 4)

    job = request(world, map_id, body=CourseRequest(request_text="  둘째 날은 실내로  ",
                                                      member_constraints=[{"kind": "daily_walk_max", "value": 60, "day": "d1"}]))

    r = row(world, job.run_id)
    assert (r.status, r.requested_by, r.map_id) == ("queued", world.uid("u1"), map_id)
    assert set(r.snapshot_pin_ids) == set(pin_ids)
    assert r.input == {"request_text": "둘째 날은 실내로",
                       "member_constraints": [{"kind": "daily_walk_max", "value": 60, "day": "d1"}]}
    assert job.build.trip is not None and len(job.build.trip.places) == 4
    assert job.build.trip.unknown_hours == "check" and len(job.build.trip.days) == 3
    assert job.build.trip.member_constraints[0].value == 60


def test_labels_come_from_known_true_facts_only(world, places):
    map_id, _ = confirmed_map(world, places, 4)
    with world.factory() as db:
        snap = service.read_snapshot(db, map_id)
    by_name = {p.name: p.labels for p in snap.pins}
    assert by_name["장소2"] == frozenset({"is_indoor"}) and by_name["장소1"] == frozenset()


def test_too_few_places_counts_only_routable_pins(world, places):
    map_id, _ = confirmed_map(world, places, 1, live=3)

    with pytest.raises(AppError) as e, world.factory() as db:
        service.request_course(db, map_id=map_id, requested_by=world.uid("u1"), body=CourseRequest(), now=world.now)

    assert code_of(e) == "COURSE_NOT_ENOUGH_PLACES" and e.value.detail == {"min": 2, "count": 1}


def test_unconfirmed_pins_do_not_count(world, places):
    map_id, _ = confirmed_map(world, places, 2)
    extra = world.pin(map_id, place_id="place_extra")          # 확정하지 않은 핀
    places.add("place_extra", "남는곳", 37.57, 126.98)
    with world.factory() as db:
        snap = service.read_snapshot(db, map_id)
    assert extra not in snap.confirmed_pin_ids and len(snap.pins) == 2


def test_in_progress_blocks_and_other_user_is_independent(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    first = request(world, map_id)

    with pytest.raises(AppError) as e, world.factory() as db:
        service.request_course(db, map_id=map_id, requested_by=world.uid("u1"), body=CourseRequest(), now=world.now)
    assert code_of(e) == "COURSE_IN_PROGRESS" and e.value.detail == {"course_run_id": first.run_id}

    assert request(world, map_id, user="u2").run_id != first.run_id


def test_stale_active_run_is_failed_instead_of_blocking_forever(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    old = request(world, map_id, now=world.now - service.STALE_AFTER - timedelta(minutes=1))

    new = request(world, map_id)

    assert row(world, old.run_id).status == "failed" and row(world, old.run_id).failure_code == "INTERRUPTED"
    assert row(world, new.run_id).status == "queued"


def test_daily_limit_counts_runs_since_kst_midnight(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    now = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)                    # KST 12:00
    kst_midnight = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    assert service.kst_day_start(now) == kst_midnight
    with world.factory() as db:
        for i in range(COURSE_DAILY_LIMIT):
            db.add(AgentCourseRun(map_id=map_id, requested_by=world.uid("u1"), status="done", input={}, snapshot_at=now,
                                  snapshot_pin_ids=[], created_at=kst_midnight + timedelta(minutes=i)))
        db.add(AgentCourseRun(map_id=map_id, requested_by=world.uid("u1"), status="done", input={}, snapshot_at=now,
                              snapshot_pin_ids=[], created_at=kst_midnight - timedelta(minutes=1)))   # 어제 KST 23:59 — 세지 않는다
        db.commit()

    with pytest.raises(AppError) as e:
        request(world, map_id, now=now)
    assert code_of(e) == "COURSE_LIMIT" and e.value.detail == {"limit": 5, "used": 5}

    assert request(world, map_id, user="u2", now=now)                           # 다른 사람은 따로 센다
    assert request(world, map_id, now=kst_midnight + timedelta(days=1, minutes=1))   # 다음 KST 날은 다시 5번


def test_member_constraint_day_outside_trip_is_422(world, places):
    map_id, _ = confirmed_map(world, places, 3)          # 3일
    with pytest.raises(AppError) as e:
        request(world, map_id, body=CourseRequest(member_constraints=[{"kind": "daily_walk_max", "value": 60, "day": "d4"}]))
    assert code_of(e) == "VALIDATION_ERROR"


def test_places_over_the_cap_are_excluded_in_confirm_order(world, places):
    map_id, pin_ids = confirmed_map(world, places, MAX_PLACES + 2)

    job = request(world, map_id)

    assert len(job.build.trip.places) == MAX_PLACES
    assert [e.pin_id for e in job.build.excluded] == pin_ids[MAX_PLACES:]
    assert {e.reason for e in job.build.excluded} == {"OVER_LIMIT"}


def test_long_trips_are_capped(world, places):
    from datetime import date
    map_id, _ = confirmed_map(world, places, 3, start=date(2026, 12, 1), end=date(2027, 2, 1))
    assert len(request(world, map_id).build.trip.days) == 14


# ---------------------------------------------------------------- 실행

def test_execute_run_saves_the_view_and_marks_done(world, places):
    map_id, pin_ids = confirmed_map(world, places, 4, live=1)
    job = request(world, map_id, body=CourseRequest(request_text=TEXT))

    service.execute_run(job, session_factory=world.factory, llm=CourseLlm(goals_planner, direct_planner()), gateway=NullOpeningHours())

    r = row(world, job.run_id)
    assert r.status == "done" and r.outcome == "solved_with_checks" and r.finished_at is not None and r.failure_code is None
    assert [g["id"] for g in r.goals] == ["day_indoor:d2"] and r.unmatched == ["웨이팅 없는 곳으로"]
    assert r.model_turns == 2
    placed = sorted(s["pin_id"] for d in r.days for s in d["slots"])
    assert placed == sorted(pin_ids[:4])
    assert [e["pin_id"] for e in r.excluded] == [pin_ids[4]] and len(r.checks) == 4
    assert r.steps[0]["stage"] == "이해"


def test_steps_grow_in_short_transactions_while_the_run_is_running(world, places):
    map_id, _ = confirmed_map(world, places, 4)
    job = request(world, map_id, body=CourseRequest(request_text=TEXT))
    observed: list[tuple[str, int]] = []
    queue = direct_planner()

    def spying(i):                 # 모델 턴마다 DB를 다른 세션으로 본다 — 앞 단계가 이미 저장돼 있어야 한다(저장이 모델을 기다리지 않는다)
        r = row(world, job.run_id)
        observed.append((r.status, len(r.steps)))
        return queue(i)

    service.execute_run(job, session_factory=world.factory, llm=CourseLlm(goals_planner, spying), gateway=NullOpeningHours())

    assert [s for s, _ in observed] == ["running", "running"]
    assert 2 <= observed[0][1] < observed[1][1]
    final = row(world, job.run_id)
    assert final.status == "done" and len(final.steps) > observed[1][1]
    assert [s["stage"] for s in final.steps][:2] == ["이해", "확인"]


def test_progress_writer_writes_the_whole_list_and_only_while_running(world, places):
    from agent.course.worklog import StepRecord
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id)
    run_id = uuid.UUID(job.run_id)
    write = service.progress_writer(world.factory, run_id)
    write(StepRecord("이해", "해석", "모델", "하나"))              # queued라서 쓰지 않는다
    assert row(world, job.run_id).steps == []
    with world.factory() as db:
        db.execute(update(AgentCourseRun).where(AgentCourseRun.id == run_id).values(status="running"))
        db.commit()
    write(StepRecord("확인", "검증", "코드", "둘"))
    assert [s["text"] for s in row(world, job.run_id).steps] == ["하나", "둘"]       # 빠진 앞 단계를 다음 저장이 메운다
    write(StepRecord("짜기", "계산", "코드", "셋"))
    assert [s["text"] for s in row(world, job.run_id).steps] == ["하나", "둘", "셋"]


def test_saved_run_has_no_place_names_in_structured_fields_and_no_coordinates(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id)
    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=NullOpeningHours())
    r = row(world, job.run_id)
    assert "장소1" not in str(r.days) and "37.56" not in str(r.days) and "126.97" not in str(r.days)
    assert "장소1" not in str(r.input) and "장소1" not in str(r.snapshot_pin_ids)


def test_engine_error_fails_the_run_without_raising(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id)

    class Boom:
        def get_opening_hours(self, place_ids):
            raise RuntimeError("secret detail 비밀")

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=Boom())

    r = row(world, job.run_id)
    assert (r.status, r.failure_code, r.outcome) == ("failed", "ENGINE_ERROR", None) and r.finished_at is not None
    assert "비밀" not in str(r.__dict__)


def test_execute_skips_a_run_that_is_no_longer_queued(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id)
    assert service.interrupt_unfinished_runs(world.factory) >= 1

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=NullOpeningHours())

    r = row(world, job.run_id)
    assert (r.status, r.failure_code) == ("failed", "INTERRUPTED") and r.days == []


def test_interrupt_unfinished_marks_queued_and_running_only(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    queued = request(world, map_id)
    running = request(world, map_id, user="u2")
    with world.factory() as db:
        db.get(AgentCourseRun, uuid.UUID(running.run_id)).status = "running"
        db.add(AgentCourseRun(map_id=map_id, requested_by=world.uid("u1"), status="done", outcome="solved", input={},
                              snapshot_at=world.now, snapshot_pin_ids=[]))
        db.commit()

    n = service.interrupt_unfinished_runs(world.factory)

    assert n >= 2
    assert {row(world, j.run_id).status for j in (queued, running)} == {"failed"}
    with world.factory() as db:
        assert db.execute(select(AgentCourseRun).where(AgentCourseRun.status == "done")).scalars().one().outcome == "solved"


# ---------------------------------------------------------------- 정리

def test_purge_and_delete_by_user(world, places):
    map_a, _ = confirmed_map(world, places, 3)
    map_b, _ = confirmed_map(world, places, 3)
    a1 = request(world, map_a)
    b1 = request(world, map_b)
    b2 = request(world, map_b, user="u2")

    with world.factory() as db:
        assert course_api.purge_map_data(db, map_ids=[map_a]) == {"agent_course_runs": 1}
        assert course_api.purge_map_data(db, map_ids=[]) == {"agent_course_runs": 0}
        db.commit()
    assert row(world, a1.run_id) is None and row(world, b1.run_id) is not None

    with world.factory() as db:
        assert course_api.delete_by_user(db, user_id=world.uid("u2")) == {"agent_course_runs": 1}
        db.commit()
    assert row(world, b2.run_id) is None and row(world, b1.run_id) is not None

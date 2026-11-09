"""AI 코스 짜기 서비스(service.py) — 실제 DB, 모델은 스텁이다. 요청 검증, 크레딧 차감·환불, 실행, 정리."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from agent.course import api as course_api, service
from agent.course.api_schemas import CourseRequest
from agent.course.constants import MAX_PLACES, RUN_LIMIT, STALE_AFTER
from agent.course.gateways import CourseLlm, NullOpeningHours
from agent.course.models import AgentCourseRun
from agent.course.tests.conftest import confirmed_map
from agent.course.tests.test_runner import TEXT, direct_planner, goals_planner
from auth.testing import make_guest
from common.errors import AppError
from credits import api as credits_api

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


def balance(world, user="u1") -> int:
    with world.factory() as db:
        return credits_api.get_balance(db, user_id=world.uid(user))


def drain(world, user="u1") -> None:
    """크레딧을 0으로 만든다 — 코스 run 없이 차감만 한다(원장과 잔액이 맞는 채로)."""
    with world.factory() as db:
        while True:
            try:
                credits_api.charge(db, user_id=world.uid(user), feature="course", run_id=str(uuid.uuid4()))
            except AppError:
                break
        db.commit()


def runs_of(world, user="u1") -> list[AgentCourseRun]:
    with world.factory() as db:
        return db.execute(select(AgentCourseRun).where(AgentCourseRun.requested_by == world.uid(user))).scalars().all()


def finish(world, run_id) -> None:
    with world.factory() as db:
        db.get(AgentCourseRun, uuid.UUID(run_id)).status = "done"
        db.commit()


# ---------------------------------------------------------------- 요청

def test_request_saves_queued_run_with_snapshot_and_input(world, places):
    map_id, pin_ids = confirmed_map(world, places, 4)

    job = request(world, map_id, body=CourseRequest(request_text="  둘째 날은 실내로  ",
                                                      member_constraints=[{"kind": "daily_walk_max", "value": 60, "day": "d1"}]))

    r = row(world, job.run_id)
    assert (r.status, r.requested_by, r.map_id) == ("queued", world.uid("u1"), map_id)
    assert r.snapshot_version and r.mode == "plan"      # 일정 version(#1237)과 모드. 날짜에 넣은 장소가 없으니 plan
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
    assert extra not in {p.pin_id for p in snap.pins} and len(snap.pins) == 2


def test_in_progress_blocks_and_other_user_is_independent(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    first = request(world, map_id)

    with pytest.raises(AppError) as e, world.factory() as db:
        service.request_course(db, map_id=map_id, requested_by=world.uid("u1"), body=CourseRequest(), now=world.now)
    assert code_of(e) == "COURSE_IN_PROGRESS" and e.value.detail == {"course_run_id": first.run_id}

    assert request(world, map_id, user="u2").run_id != first.run_id


def test_stale_active_run_is_failed_instead_of_blocking_forever(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    old = request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))

    new = request(world, map_id)

    assert row(world, old.run_id).status == "failed" and row(world, old.run_id).failure_code == "INTERRUPTED"
    assert row(world, new.run_id).status == "queued"


def test_request_charges_one_credit_for_the_run(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)

    job = request(world, map_id)

    assert balance(world) == before - 1
    with world.factory() as db:                    # 차감은 그 run에 묶였다 — 그 run id로 돌려줄 수 있다
        assert credits_api.refund(db, feature="course", run_id=job.run_id) is True
        db.rollback()


def test_sixth_request_passes_without_a_daily_limit(world, places):
    """하루 5회 상한은 크레딧으로 바뀌었다(#432 D3, 명세 12절 14). 잔액이 있으면 몇 번째든 통과한다."""
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    for _ in range(6):
        finish(world, request(world, map_id).run_id)          # 끝내야 다음 요청이 COURSE_IN_PROGRESS에 막히지 않는다

    assert len(runs_of(world)) == 6 and balance(world) == before - 6


def test_insufficient_credit_is_402_and_leaves_no_run(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    drain(world)

    with pytest.raises(AppError) as e:
        request(world, map_id)

    assert code_of(e) == "CREDIT_INSUFFICIENT" and e.value.detail == {"required": 1, "balance": 0}
    assert runs_of(world) == []


def test_guest_is_403_and_leaves_no_run(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    with world.factory() as db:
        make_guest(db, world.uid("u1"))
        db.commit()

    with pytest.raises(AppError) as e:
        request(world, map_id)

    assert code_of(e) == "GUEST_NOT_ALLOWED" and "initial_credits" in e.value.detail
    assert runs_of(world) == []


def test_in_progress_409_does_not_charge(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    request(world, map_id)
    after_first = balance(world)

    with pytest.raises(AppError):
        request(world, map_id)

    assert balance(world) == after_first


def test_interrupted_run_is_refunded_once(world, places):
    """INTERRUPTED로 끝난 run의 크레딧이 돌아온다. 두 번 끝내도(요청, 조회, 서버 시작) 한 번만(명세 12절 15)."""
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    old = request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))
    assert balance(world) == before - 1

    with world.factory() as db:
        assert service.fail_stale_runs(db, run_id=uuid.UUID(old.run_id), now=world.now) == 1
        db.commit()
    assert balance(world) == before

    with world.factory() as db:                    # 이미 끝난 run은 다시 걸리지 않고, 환불을 직접 다시 불러도 늘지 않는다
        assert service.fail_stale_runs(db, run_id=uuid.UUID(old.run_id), now=world.now) == 0
        service.refund_credit(db, uuid.UUID(old.run_id))
        db.commit()
    assert balance(world) == before


def test_startup_interrupt_refunds_each_run(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    old_age = world.now - STALE_AFTER - timedelta(minutes=1)
    before = {u: balance(world, u) for u in ("u1", "u2")}
    for u in ("u1", "u2"):
        request(world, map_id, user=u, now=old_age)

    assert service.interrupt_unfinished_runs(world.factory, now=world.now) == 2

    assert {u: balance(world, u) for u in ("u1", "u2")} == before


def test_stale_run_on_new_request_is_refunded_and_new_one_charged(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))

    request(world, map_id)                          # 오래된 run을 끝내며 돌려주고, 새 run에 1을 뺀다

    assert balance(world) == before - 1


# 끊긴 run을 끝내는 세 길(#1609) — 요청(지도+사람), 조회(run id, latest의 지도+사람), 서버 시작(전체). 판정은 STALE_AFTER 하나다
STALE_PATHS = ("request", "lookup", "startup")


def clean_up(world, map_id, job, path) -> None:
    """router와 main.py가 부르는 그대로. 요청 길은 새 run을 요청한다(진행 중이 남아 있으면 COURSE_IN_PROGRESS)."""
    if path == "request":
        request(world, map_id)
    elif path == "lookup":
        with world.factory() as db:
            service.fail_stale_runs(db, run_id=uuid.UUID(job.run_id), now=world.now)                  # GET /course-runs/{runId}
            service.fail_stale_runs(db, map_id=map_id, requested_by=world.uid("u1"), now=world.now)   # GET /maps/{mapId}/courses/latest
            db.commit()
    else:
        service.interrupt_unfinished_runs(world.factory, now=world.now)


@pytest.mark.parametrize("path", STALE_PATHS)
def test_run_past_stale_after_is_interrupted_on_every_path_and_refunded_once(world, places, path):
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    old = request(world, map_id, now=world.now - STALE_AFTER - timedelta(seconds=1))

    clean_up(world, map_id, old, path)
    for again in ("lookup", "startup"):            # 다른 길이 다시 끝내려 해도 이미 끝난 run이라 환불이 늘지 않는다
        clean_up(world, map_id, old, again)

    r = row(world, old.run_id)
    assert (r.status, r.failure_code) == ("failed", "INTERRUPTED")
    assert balance(world) == before - (1 if path == "request" else 0)      # 요청 길은 새 run에 1을 쓴다


@pytest.mark.parametrize("path", STALE_PATHS)
def test_run_inside_stale_after_is_left_alone_on_every_path(world, places, path):
    """상한은 지났어도 여유 안이면 상한 직전에 시작한 모델 호출을 마무리하는 중일 수 있다 — 어느 길도 끝내지 않는다."""
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    job = request(world, map_id, now=world.now - STALE_AFTER + timedelta(seconds=5))

    if path == "request":
        with pytest.raises(AppError) as e:
            clean_up(world, map_id, job, path)
        assert code_of(e) == "COURSE_IN_PROGRESS"
    else:
        clean_up(world, map_id, job, path)

    assert row(world, job.run_id).status == "queued" and balance(world) == before - 1


def test_stale_after_is_the_run_limit_plus_a_margin():
    """끊긴 run 판정은 실행 상한에서 나온다 — 상한을 바꾸면 판정도 따라간다(#1609)."""
    assert RUN_LIMIT < STALE_AFTER <= RUN_LIMIT * 2


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


def test_execute_run_past_the_limit_skips_the_model_and_saves_done(world, places):
    """큐에서 기다리다 실행 상한이 지난 run — 기준 시각은 created_at이다(판정과 같은 기준). 모델을 부르지 않고 코드 규칙이 마무리해
    done으로 저장하고, 작업 기록에 상한 단계를 남긴다(#1609)."""
    map_id, _ = confirmed_map(world, places, 4)
    job = request(world, map_id, body=CourseRequest(request_text=TEXT), now=world.now - RUN_LIMIT - timedelta(seconds=1))
    calls = []

    def spy(i):
        calls.append(i)
        raise AssertionError("상한이 지난 run은 모델을 부르지 않는다")

    service.execute_run(job, session_factory=world.factory, llm=CourseLlm(spy, spy), gateway=NullOpeningHours())

    r = row(world, job.run_id)
    assert calls == [] and r.status == "done" and r.failure_code is None and r.model_turns == 0
    assert r.unmatched == [TEXT] and any(s["text"].startswith("실행 시간 상한이 되어") for s in r.steps)


def test_model_calls_carry_the_requester_usage_label(world, places):
    """목표 세우기와 지휘 턴은 사용량 기록(llm_calls, #870)에 course로 남는다 — 요청자, 지도, 코스 run이 붙고 한 trace다."""
    from llm import usage

    map_id, _ = confirmed_map(world, places, 4)
    job = request(world, map_id, body=CourseRequest(request_text=TEXT))
    labels = []
    queue = direct_planner()

    def labelled_goals(goals_input):
        labels.append(usage.current_label())
        return goals_planner(goals_input)

    def labelled_direct(turn_input):
        labels.append(usage.current_label())
        return queue(turn_input)

    service.execute_run(job, session_factory=world.factory, llm=CourseLlm(labelled_goals, labelled_direct),
                        gateway=NullOpeningHours())

    assert len(labels) >= 2
    assert {(l.feature, l.map_id, l.user_id, l.run_id) for l in labels} == {("course", map_id, world.uid("u1"), job.run_id)}
    assert len({l.trace_id for l in labels}) == 1


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
    assert "장소1" not in str(r.input) and "장소1" not in str(r.snapshot_version)


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


def test_engine_error_refunds_the_credit_once(world, places):
    """ENGINE_ERROR로 끝난 run의 크레딧이 돌아온다. 뒤이은 정리가 다시 끝내려 해도 한 번만(명세 12절 15)."""
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    job = request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))

    class Boom:
        def get_opening_hours(self, place_ids):
            raise RuntimeError("boom")

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=Boom())
    assert balance(world) == before

    with world.factory() as db:                    # 이미 failed라 정리에 걸리지 않고, 환불을 다시 불러도 늘지 않는다
        assert service.fail_stale_runs(db, run_id=uuid.UUID(job.run_id), now=world.now) == 0
        service.refund_credit(db, uuid.UUID(job.run_id))
        db.commit()
    assert balance(world) == before


def test_done_run_keeps_the_charge(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    before = balance(world)
    job = request(world, map_id)

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=NullOpeningHours())

    assert row(world, job.run_id).status == "done" and balance(world) == before - 1


def test_execute_skips_a_run_that_is_no_longer_queued(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))
    assert service.interrupt_unfinished_runs(world.factory, now=world.now) >= 1

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=NullOpeningHours())

    r = row(world, job.run_id)
    assert (r.status, r.failure_code) == ("failed", "INTERRUPTED") and r.days == []


def test_late_finishing_run_does_not_overwrite_an_interrupted_one(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    job = request(world, map_id, now=world.now - STALE_AFTER - timedelta(minutes=1))
    class InterruptedMidRun:
        def get_opening_hours(self, place_ids):         # 계산 도중 조회가 오래된 run을 끝낸다
            with world.factory() as db:
                assert service.fail_stale_runs(db, run_id=uuid.UUID(job.run_id), now=world.now) == 1
                db.commit()
            return {}

    service.execute_run(job, session_factory=world.factory, llm=NO_MODEL, gateway=InterruptedMidRun())

    r = row(world, job.run_id)
    assert (r.status, r.failure_code) == ("failed", "INTERRUPTED") and r.days == [] and r.outcome is None


def test_startup_interrupts_only_old_active_runs(world, places):
    map_id, _ = confirmed_map(world, places, 3)
    old_age = world.now - STALE_AFTER - timedelta(minutes=1)
    old_queued = request(world, map_id, now=old_age)
    old_running = request(world, map_id, user="u2", now=old_age)
    recent_running = request(world, map_id, user="u3", now=world.now - timedelta(minutes=1))    # 1분 된 run(#1609)
    with world.factory() as db:
        for job in (old_running, recent_running):
            db.get(AgentCourseRun, uuid.UUID(job.run_id)).status = "running"
        db.add(AgentCourseRun(map_id=map_id, requested_by=world.uid("u1"), status="done", outcome="solved", input={},
                              snapshot_at=old_age, snapshot_version="v", created_at=old_age))
        db.commit()

    n = service.interrupt_unfinished_runs(world.factory, now=world.now)

    assert n == 2
    for job in (old_queued, old_running):
        r = row(world, job.run_id)
        assert (r.status, r.failure_code) == ("failed", "INTERRUPTED") and r.finished_at is not None
    assert row(world, recent_running.run_id).status == "running"      # STALE_AFTER 안의 run은 다른 프로세스에서 도는 것일 수 있어 둔다
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


# ---------------------------------------------------------------- 일정 기준 모드와 version (#1321)

def _mode_of(world, map_id):
    with world.factory() as db:
        job = service.request_course(db, map_id=map_id, requested_by=world.uid("u1"), body=CourseRequest(), now=world.now)
        db.commit()
    return job, row(world, job.run_id)


def test_mode_is_decided_at_request_from_the_schedule_state(world, places):
    from agent.course.tests.conftest import schedule_pins

    plan_map, _ = confirmed_map(world, places, 4)
    job, r = _mode_of(world, plan_map)
    assert (r.mode, job.build.mode, dict(job.build.locks)) == ("plan", "plan", {})

    fill_map, ids = confirmed_map(world, places, 4)
    schedule_pins(world, fill_map, {ids[0]: 0, ids[1]: 2})
    job, r = _mode_of(world, fill_map)
    assert (r.mode, len(job.build.locks)) == ("fill", 2) and set(job.build.locks.values()) == {"d1", "d3"}

    review_map, ids = confirmed_map(world, places, 4)
    schedule_pins(world, review_map, {ids[0]: 0, ids[1]: 0, ids[2]: 1, ids[3]: 2})
    job, r = _mode_of(world, review_map)
    assert r.mode == "review" and job.build.schedule == (("p1", "p2"), ("p3",), ("p4",))


def test_snapshot_version_changes_when_only_the_schedule_changes(world, places):
    from agent.course.tests.conftest import schedule_pins

    map_id, ids = confirmed_map(world, places, 4)
    with world.factory() as db:
        before = service.read_snapshot(db, map_id).version
    schedule_pins(world, map_id, {ids[0]: 1})            # 장소는 그대로, 날짜만 바뀐다
    with world.factory() as db:
        after = service.read_snapshot(db, map_id).version
        assert after != before and service.current_schedule_version(db, map_id) == after

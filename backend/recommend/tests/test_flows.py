"""flows.py::publish_candidate — mentor-review-plan.md "검증" 절의 각 행을 그대로 테스트한다.
실제 PostgreSQL이 필요하다(db_session/test_engine, conftest.py 참고)."""

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from authz.testing import FakeMembership
from common.errors import AppError
from common.events import EventLog
from pins.models import Pin as PinRow
from recommend import flows, service
from recommend.models import Candidate, RecommendRun


def _make_run(db_session, **overrides):
    defaults = {
        "id": uuid.uuid4(), "map_id": "map_1", "category": "음식점",
        "requested_by": "user_1", "status": "done",
    }
    defaults.update(overrides)
    run = RecommendRun(**defaults)
    db_session.add(run)
    db_session.flush()
    return run


def _make_candidate(db_session, run, **overrides):
    defaults = {
        "id": uuid.uuid4(), "run_id": run.id, "place_id": f"place_{uuid.uuid4().hex[:8]}",
        "lat": 35.1, "lng": 129.0, "rank": 1,
    }
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.flush()
    return candidate


def _membership(map_id, user_id, role="member"):
    return FakeMembership({(map_id, user_id): role})


def test_publish_candidate_inserts_ai_pin_links_candidate_and_records_event(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)

    pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )

    assert pin.kind == "AI추천"
    assert pin.origin == "ai"
    assert pin.place_id == candidate.place_id

    db_session.refresh(candidate)
    assert candidate.published_pin_id == pin.id

    events = db_session.execute(select(EventLog).where(EventLog.map_id == run.map_id)).scalars().all()
    assert len(events) == 1
    assert events[0].type == "pin.published"  # docs/events.md — pins.api의 pin.created가 아니다


def test_publish_candidate_non_member_is_not_found(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="stranger",
            membership=_membership(run.map_id, "user_1"),  # stranger는 role 없음
        )
    assert exc_info.value.code == "NOT_FOUND"

    db_session.refresh(candidate)
    assert candidate.published_pin_id is None  # 멱등 경로까지 도달하지 않는다


def test_publish_candidate_non_author_member_is_forbidden(db_session):
    """recommend.publish는 candidate.requested_by 본인만 가능(authz/policy.py
    AUTHOR_CONSTRAINED_ACTIONS) — 같은 지도 구성원이라도 본인이 아니면 403.
    docs/permissions.md의 404(비구성원)/403(구성원인데 액션 불가) 두 값 중 후자다."""
    run = _make_run(db_session, requested_by="user_1")
    candidate = _make_candidate(db_session, run)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_2",
            membership=_membership(run.map_id, "user_2"),  # 같은 지도 구성원이지만 run 요청자 본인이 아니다
        )
    assert exc_info.value.code == "FORBIDDEN"


def test_publish_candidate_run_not_done_is_not_ready(db_session):
    run = _make_run(db_session, status="executing")
    candidate = _make_candidate(db_session, run)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_1",
            membership=_membership(run.map_id, "user_1"),
        )
    assert exc_info.value.code == "NOT_READY"


def test_publish_candidate_twice_second_call_is_idempotent_with_no_new_event(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)

    first_pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )
    second_pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )

    assert second_pin.id == first_pin.id
    events = db_session.execute(select(EventLog).where(EventLog.map_id == run.map_id)).scalars().all()
    assert len(events) == 1  # 두 번째 호출은 이벤트를 추가하지 않는다


def test_publish_candidate_idempotent_path_propagates_pin_not_found(db_session):
    """대상 핀이 그 사이 삭제/비공개 전환된 상태를 흉내 — get_pin_for_viewer의 예외가
    그대로 전파돼야 한다(별도 재게시 로직 없음)."""
    run = _make_run(db_session)
    ghost_pin_id = uuid.uuid4()  # pins 테이블엔 존재하지 않는 id
    candidate = _make_candidate(db_session, run, published_pin_id=ghost_pin_id)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_1",
            membership=_membership(run.map_id, "user_1"),
        )
    assert exc_info.value.code == "NOT_FOUND"


def test_publish_candidate_duplicate_place_id_rolls_back_everything(db_session):
    """create_ai_pin이 uq_pins_map_place 위반(IntegrityError)으로 PIN_DUPLICATE를 던지면
    candidates.published_pin_id도 event_log도 안 바뀐다 — 세이브포인트 롤백이 실패한
    삽입만 되돌린다(pins/for_Root.md의 begin_nested 버그 수정과 같은 보장)."""
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run, place_id="dup_place")
    existing = PinRow(
        id=uuid.uuid4(), map_id=run.map_id, category="음식점", kind="일반", origin="direct",
        place_id="dup_place",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(existing)
    db_session.commit()  # 기준선 — 아래 실패가 여기까지 되돌리지 않는지 확인하는 게 목적

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_1",
            membership=_membership(run.map_id, "user_1"),
        )
    assert exc_info.value.code == "PIN_DUPLICATE"
    db_session.rollback()  # common/database.py get_db와 동일

    db_session.refresh(candidate)
    assert candidate.published_pin_id is None
    events = db_session.execute(select(EventLog).where(EventLog.map_id == run.map_id)).scalars().all()
    assert events == []


def test_publish_candidate_guard_update_conflict_rolls_back_pin_insert(db_session, monkeypatch):
    """link_published_pin의 가드 UPDATE가 rowcount==0을 반환하도록 강제로 흉내 낸 경우 —
    409 IDEMPOTENCY_CONFLICT, 그리고 직전에 생긴 pins INSERT까지 함께 롤백돼 고아 행이
    안 남는지 확인한다(mentor-review-plan.md 레이스 2번)."""
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)
    db_session.commit()  # 기준선

    def _fake_link_published_pin(db, *, candidate_id, pin_id):
        raise AppError("IDEMPOTENCY_CONFLICT")

    monkeypatch.setattr(service, "link_published_pin", _fake_link_published_pin)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_1",
            membership=_membership(run.map_id, "user_1"),
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"
    db_session.rollback()  # common/database.py get_db와 동일

    db_session.refresh(candidate)
    assert candidate.published_pin_id is None

    rows = db_session.execute(
        select(PinRow).where(PinRow.map_id == run.map_id, PinRow.place_id == candidate.place_id)
    ).scalars().all()
    assert rows == []  # 직전 pins INSERT까지 함께 롤백 — 고아 행 없음


def test_concurrent_publish_same_candidate_produces_exactly_one_pin(test_engine, monkeypatch):
    """동시에 두 요청을 보내 같은 후보를 게시하는 시나리오(세션 두 개로 흉내) — 하나는
    200(생성), 다른 하나는 409 PIN_DUPLICATE(IDEMPOTENCY_CONFLICT가 아니다). 최종적으로
    pins 행은 정확히 1개. db_session(세이브포인트, 롤백 전용) 대신 test_engine에 직접
    연결한다 — 실제 유니크 제약 락 경합을 재현하려면 진짜 커밋이 필요하다.

    스레드 시작 시점만 맞추는 barrier로는 실제 경합이 안 났다(로컬 DB 왕복이 빨라 한 스레드가
    커밋까지 끝내버려 두 번째가 멱등 경로를 타는 걸 직접 확인함) — `load_candidate_with_run`
    직후(= "아직 게시 안 됨"을 두 스레드 다 확인한 시점)에 두 번째 barrier를 걸어, 두 스레드가
    `pins_api.create_ai_pin`의 INSERT에 실제로 동시에 들어가도록 강제한다."""
    Session = sessionmaker(bind=test_engine)

    run_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    setup = Session()
    setup.add(RecommendRun(id=run_id, map_id="map_race", category="음식점", requested_by="racer", status="done"))
    setup.flush()  # candidates.run_id FK가 가리킬 행을 먼저 커밋 큐에 넣는다 — models.py에 ORM
    # relationship()이 없어(pins.models와 같은 스타일) 한 flush에 같이 넣으면 unit of work가
    # 테이블명 순서(candidates가 recommend_runs보다 먼저)로 삽입해 FK 위반이 난다(직접 확인).
    setup.add(Candidate(id=candidate_id, run_id=run_id, place_id="place_race", lat=35.1, lng=129.0, rank=1))
    setup.commit()
    setup.close()

    membership = _membership("map_race", "racer")
    results: list[tuple[str, object]] = []
    start_barrier = threading.Barrier(2)
    insert_barrier = threading.Barrier(2)

    original_load = service.load_candidate_with_run

    def _load_then_sync_before_insert(db, candidate_id):
        result = original_load(db, candidate_id)
        insert_barrier.wait(timeout=5)  # 둘 다 published_pin_id=None을 읽은 뒤에야 동시에 푼다
        return result

    monkeypatch.setattr(service, "load_candidate_with_run", _load_then_sync_before_insert)

    def _attempt():
        session = Session()
        start_barrier.wait()
        try:
            pin = flows.publish_candidate(
                session, candidate_id=str(candidate_id), requester_id="racer", membership=membership,
            )
            session.commit()
            results.append(("ok", pin.id))
        except AppError as exc:
            session.rollback()
            results.append(("error", exc.code))
        finally:
            session.close()

    threads = [threading.Thread(target=_attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    oks = [r for r in results if r[0] == "ok"]
    errors = [r for r in results if r[0] == "error"]
    assert len(oks) == 1
    assert len(errors) == 1
    assert errors[0][1] == "PIN_DUPLICATE"

    verify = Session()
    try:
        pin_count = verify.execute(
            select(func.count()).select_from(PinRow).where(PinRow.map_id == "map_race")
        ).scalar_one()
        assert pin_count == 1
    finally:
        verify.execute(delete(PinRow).where(PinRow.map_id == "map_race"))
        verify.execute(delete(Candidate).where(Candidate.id == candidate_id))
        verify.execute(delete(RecommendRun).where(RecommendRun.id == run_id))
        verify.commit()
        verify.close()

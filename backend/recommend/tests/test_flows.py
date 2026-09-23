"""flows.py 전체 — publish_candidate(mentor-review-plan.md "검증" 절)와 #108 코어 파이프라인
(readiness/run 생성/evidence/지역확인/실행/결과/반경넓히기/재시도) 둘 다. 실제 PostgreSQL이
필요하다(db_session/test_engine, conftest.py 참고)."""

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from authz.testing import FakeMembership
from common.errors import AppError
from common.events import EventLog
from maps.models import Membership as MembershipRow
from pins import api as pins_api
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from recommend import flows, service
from recommend.models import Candidate, RecommendRun, Region
from recommend.ports import PlaceStub


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


def _make_pin(db_session, *, map_id="map_1", category="음식점", lat=35.1, lng=129.0, created_by="user_1"):
    pin = PinRow(
        id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        visibility="public", created_by=created_by,
    )
    db_session.add(pin)
    db_session.flush()
    return pin


def _react(db_session, pin, *, user_id, type="like", reason_text=None):
    reaction = ReactionRow(pin_id=pin.id, user_id=user_id, type=type, reason_text=reason_text)
    db_session.add(reaction)
    db_session.flush()
    return reaction


def _make_members(db_session, *, map_id="map_1", user_ids):
    # memberships.map_id -> maps.id FK(0005_maps.py 이후 추가) — 참조할 Map 행이 먼저 있어야 한다.
    from maps.models import Map as MapRow

    if db_session.get(MapRow, map_id) is None:
        db_session.add(MapRow(
            id=map_id, title="테스트 지도", start_date="2026-01-01", end_date="2026-01-02", created_by="owner_1",
        ))
        db_session.flush()
    for user_id in user_ids:
        db_session.add(MembershipRow(map_id=map_id, user_id=user_id, role="member"))
    db_session.flush()


class _FakePlaceSearch:
    def __init__(self, places):
        self._places = places

    def search_nearby(self, *, category, circles):
        return self._places


class _FakePlaceFacts:
    def __init__(self, facts_by_place=None):
        self._facts = facts_by_place or {}

    def get_raw_facts(self, place_id):
        return self._facts.get(place_id, {})


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


def test_publish_candidate_copies_candidate_checks_to_pin(db_session):
    """#124/#57 — 게시 시점에 candidate.checks가 pins.checks로 복사되고, 게시 뒤 유지된다
    (가드레일 5). pins.api.create_ai_pin(checks=...)/pins.schemas.Check 경계 검증까지 실제
    PostgreSQL로 왕복 확인한다."""
    run = _make_run(db_session)
    checks = [
        {"fact_key": "contains_shellfish", "label": "조개류 포함", "passed": True,
         "confidence": "known", "needs_check": False},
        {"fact_key": "price_bucket", "label": "가격대", "passed": True,
         "confidence": "unknown", "needs_check": True},
    ]
    candidate = _make_candidate(db_session, run, checks=checks)

    pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )

    db_session.expire_all()  # DB에서 다시 읽는다 — flows.py가 세션에 든 파이썬 객체를 그대로 돌려준 게 아닌지 확인
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    response = pins_api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_1", principal=principal,
    )
    assert [c.model_dump() for c in response.checks] == checks

    # write-once — 게시 뒤 candidate.checks를 바꿔도 이미 복사된 pins.checks는 그대로다.
    candidate.checks = [{"fact_key": "spicy_focused", "label": "매운맛 위주", "passed": False,
                         "confidence": "known", "needs_check": False}]
    db_session.flush()
    db_session.expire_all()
    response_after = pins_api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_1", principal=principal,
    )
    assert [c.model_dump() for c in response_after.checks] == checks


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


# ============================================================================
# #108 — 코어 파이프라인
# ============================================================================

def test_get_readiness_counts_distinct_reacted_users_per_category(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2", "user_3"])  # required = ceil(3/2) = 2
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")

    readiness = flows.get_readiness(db_session, map_id="map_1")

    assert readiness["음식점"] == {"ready": False, "answered_count": 1, "required_count": 2}
    assert readiness["카페"] == {"ready": False, "answered_count": 0, "required_count": 2}


def test_get_readiness_ready_when_enough_distinct_users_reacted(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2"])  # required = 1
    pin = _make_pin(db_session, category="카페")
    _react(db_session, pin, user_id="user_1", type="neutral")

    readiness = flows.get_readiness(db_session, map_id="map_1")
    assert readiness["카페"]["ready"] is True


def test_create_run_raises_not_ready_when_readiness_fails(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2"])  # required = 1, 아무도 반응 안 함
    with pytest.raises(AppError) as exc_info:
        flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")
    assert exc_info.value.code == "NOT_READY"


def test_create_run_succeeds_assembles_evidence_and_default_region(db_session):
    _make_members(db_session, user_ids=["user_1"])  # required = 1
    pin = _make_pin(db_session, category="음식점", lat=35.2, lng=129.3)
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert run.status == "collecting_evidence"
    assert run.attempt_no == 1

    lines = service.list_evidence(db_session, str(run.id))
    assert len(lines) == 1
    assert lines[0].source == "reaction"
    assert lines[0].badge == "required"  # 반대(against) → required로 잠정 매핑
    assert lines[0].text == "너무 매워요"

    regions = service.list_regions(db_session, str(run.id))
    assert len(regions) == 1
    assert regions[0].confirmed is True
    assert regions[0].center_lat == pytest.approx(35.2)
    assert regions[0].center_lng == pytest.approx(129.3)
    assert regions[0].radius_m == flows.DEFAULT_REGION_RADIUS_M


def test_create_run_raises_retry_limit_when_already_exhausted(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="카페")
    _react(db_session, pin, user_id="user_1", type="like")
    _make_run(db_session, map_id="map_1", requested_by="user_1", category="음식점", attempt_no=5)

    with pytest.raises(AppError) as exc_info:
        flows.create_run(db_session, map_id="map_1", category="카페", requested_by="user_1")  # 카테고리 무관(#31)
    assert exc_info.value.code == "RETRY_LIMIT"


# ---------- evidence ----------

def test_list_evidence_reports_can_disable_only_for_author(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "a", "badge": "required", "fact_key": None},
    ])
    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    lines = flows.list_evidence(db_session, run_id=str(run.id), principal=principal)
    assert lines[0].permissions.can_disable is True

    other = Principal(user_id="user_2", map_id="map_1", role="member")
    lines = flows.list_evidence(db_session, run_id=str(run.id), principal=other)
    assert lines[0].permissions.can_disable is False


def test_patch_evidence_toggle_own_line_succeeds(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "a", "badge": "required", "fact_key": None},
    ])
    [line] = service.list_evidence(db_session, str(run.id))
    principal = Principal(user_id="user_1", map_id="map_1", role="member")

    result = flows.patch_evidence(
        db_session, run_id=str(run.id), principal=principal,
        toggles=[(str(line.id), False)], adds=[],
    )
    assert result[0].is_active is False


def test_patch_evidence_toggle_other_users_line_is_forbidden(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "a", "badge": "required", "fact_key": None},
    ])
    [line] = service.list_evidence(db_session, str(run.id))
    principal = Principal(user_id="user_2", map_id="map_1", role="member")

    with pytest.raises(AppError) as exc_info:
        flows.patch_evidence(db_session, run_id=str(run.id), principal=principal, toggles=[(str(line.id), False)], adds=[])
    assert exc_info.value.code == "FORBIDDEN"


def test_patch_evidence_add_creates_manual_reference_line(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    principal = Principal(user_id="user_1", map_id="map_1", role="member")

    result = flows.patch_evidence(db_session, run_id=str(run.id), principal=principal, toggles=[], adds=["주차 필요해요"])
    assert len(result) == 1
    assert result[0].text == "주차 필요해요"
    assert result[0].badge == "reference"


# ---------- regions confirm ----------

def test_confirm_regions_sets_status_executing_when_already_confirmed(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    db_session.add(Region(
        run_id=run.id, signature="sig", label="기본 반경", center_lat=35.0, center_lng=129.0,
        radius_m=2000, confirmed=True,
    ))
    db_session.flush()

    regions = flows.confirm_regions(db_session, run_id=str(run.id), accept_union=False)
    assert regions[0].confirmed is True
    db_session.refresh(run)
    assert run.status == "executing"


def test_confirm_regions_conflict_when_unconfirmed_and_no_accept_union(db_session):
    run = _make_run(db_session, status="awaiting_region_confirm")
    db_session.add_all([
        Region(run_id=run.id, signature="a", label="지역A", center_lat=35.0, center_lng=129.0, radius_m=500, confirmed=False),
        Region(run_id=run.id, signature="b", label="지역B", center_lat=36.0, center_lng=130.0, radius_m=500, confirmed=False),
    ])
    db_session.flush()

    with pytest.raises(AppError) as exc_info:
        flows.confirm_regions(db_session, run_id=str(run.id), accept_union=False)
    assert exc_info.value.code == "REGION_CONFLICT"


def test_confirm_regions_accept_union_confirms_all(db_session):
    run = _make_run(db_session, status="awaiting_region_confirm")
    db_session.add_all([
        Region(run_id=run.id, signature="a", label="지역A", center_lat=35.0, center_lng=129.0, radius_m=500, confirmed=False),
        Region(run_id=run.id, signature="b", label="지역B", center_lat=36.0, center_lng=130.0, radius_m=500, confirmed=False),
    ])
    db_session.flush()

    regions = flows.confirm_regions(db_session, run_id=str(run.id), accept_union=True)
    assert all(r.confirmed for r in regions)


# ---------- execute / result ----------

def _make_region(db_session, run, *, center_lat=35.0, center_lng=129.0, radius_m=2000, label="기본 반경"):
    region = Region(
        run_id=run.id, signature="sig", label=label, center_lat=center_lat, center_lng=center_lng,
        radius_m=radius_m, confirmed=True,
    )
    db_session.add(region)
    db_session.flush()
    return region


def test_execute_run_full_funnel_removes_out_of_radius_disqualified_and_excluded(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "매운거 빼주세요",
         "badge": "required", "fact_key": "spicy_focused"},
    ])
    service.add_exclusions(
        db_session, map_id="map_1", category="음식점", place_ids=["excluded_place"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )

    places = [
        PlaceStub(place_id="ok_place", lat=35.0005, lng=129.0005),       # 반경 안, 실격 아님(known) → 통과
        PlaceStub(place_id="spicy_place", lat=35.0005, lng=129.0006),    # 반경 안, 매운맛(known) → 실격
        PlaceStub(place_id="far_place", lat=40.0, lng=135.0),            # 반경 밖 → 제거
        PlaceStub(place_id="excluded_place", lat=35.0004, lng=129.0004),  # 반경 안, 실격 아님(known), 제외목록 → 제거
    ]
    place_search = _FakePlaceSearch(places)
    # spicy_focused는 unknown_policy=exclude(가드레일8) — known 값을 명시해야 실격이 "매움" 하나로만
    # 갈린다. facts에 없는 far_place는 반경 필터에서 이미 빠져 라벨링 자체를 안 받는다.
    place_facts = _FakePlaceFacts({
        "ok_place": {"spicy_focused": False},
        "spicy_place": {"spicy_focused": True},
        "excluded_place": {"spicy_focused": False},
    })

    updated = flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    assert updated.status == "done"
    candidates = service.list_candidates(db_session, str(run.id))
    assert [c.place_id for c in candidates] == ["ok_place"]

    funnel = {entry["label"]: entry["removed_count"] for entry in updated.last_funnel}
    assert funnel["반경 밖 제거"] == 1
    assert funnel["실격 조건 제거"] == 1
    assert funnel["이미 제안·거절됨"] == 1

    events = db_session.execute(
        select(EventLog).where(EventLog.type == "run.candidates_ready")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].channel == "private"
    assert events[0].recipient_user_id == "user_1"


def test_execute_run_excludes_place_ids_already_pinned_on_the_map(db_session):
    """루트 수정(2026-09-23) — 이전엔 exclusions 테이블만 봐서, 이미 지도에 있는 핀(수동이든
    다른 run이 게시한 것이든)의 place_id가 그대로 다시 추천될 수 있었다. 게시하려는 순간
    pins.unique(map_id, place_id) 위반으로 PIN_DUPLICATE만 반복되는 문제라 여기서 미리 뺀다."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)

    existing_pin = PinRow(
        id=uuid.uuid4(), map_id="map_1", category="음식점", kind="일반", origin="direct",
        place_id="already_pinned", geom=func.ST_SetSRID(func.ST_MakePoint(129.0005, 35.0005), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(existing_pin)
    db_session.flush()

    places = [
        PlaceStub(place_id="already_pinned", lat=35.0005, lng=129.0005),
        PlaceStub(place_id="new_place", lat=35.0006, lng=129.0006),
    ]
    place_search = _FakePlaceSearch(places)
    place_facts = _FakePlaceFacts({"already_pinned": {}, "new_place": {}})

    flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    candidates = service.list_candidates(db_session, str(run.id))
    assert [c.place_id for c in candidates] == ["new_place"]


def test_execute_run_unknown_safety_fact_is_excluded_not_needs_check(db_session):
    """가드레일8 — 안전 조건(spicy_focused)이 unknown이면 pass+needs_check가 아니라 제거된다."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "매운거 빼주세요",
         "badge": "required", "fact_key": "spicy_focused"},
    ])
    places = [PlaceStub(place_id="unknown_place", lat=35.0005, lng=129.0005)]
    place_search = _FakePlaceSearch(places)
    place_facts = _FakePlaceFacts({})  # spicy_focused 원자료 없음 → unknown

    flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    candidates = service.list_candidates(db_session, str(run.id))
    assert candidates == []  # exclude 정책 — unknown인데 통과시키지 않는다


def test_execute_run_with_no_candidates_then_get_result_is_no_results(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run)
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts())

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    with pytest.raises(AppError) as exc_info:
        flows.get_result(db_session, run_id=str(run.id), principal=principal)
    assert exc_info.value.code == "NO_RESULTS"
    assert "funnel" in exc_info.value.detail


def test_get_result_marks_can_publish_true_only_for_run_author(db_session):
    run = _make_run(db_session, status="collecting_evidence", requested_by="user_1")
    _make_region(db_session, run)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts())

    author = Principal(user_id="user_1", map_id="map_1", role="member")
    result = flows.get_result(db_session, run_id=str(run.id), principal=author)
    assert result.candidates[0].permissions.can_publish is True

    stranger = Principal(user_id="user_2", map_id="map_1", role="member")
    result2 = flows.get_result(db_session, run_id=str(run.id), principal=stranger)
    assert result2.candidates[0].permissions.can_publish is False


def test_get_result_marks_can_publish_false_once_already_published(db_session):
    """루트 수정(2026-09-23) — can()은 requested_by만 보고 published_pin_id를 모른다. 이미
    게시된 candidate까지 작성자에게 can_publish=true를 내려주면 FE가 게시 버튼을 계속 활성화된
    채로 그린다(docs/data-model.md에 미리 남겨둔 주의사항, #108 구현이 놓쳤던 부분)."""
    run = _make_run(db_session, status="collecting_evidence", requested_by="user_1")
    _make_region(db_session, run)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts())

    author = Principal(user_id="user_1", map_id="map_1", role="member")
    candidate = service.list_candidates(db_session, str(run.id))[0]
    service.link_published_pin(db_session, candidate_id=str(candidate.id), pin_id=str(uuid.uuid4()))

    result = flows.get_result(db_session, run_id=str(run.id), principal=author)
    assert result.candidates[0].visibility == "published"
    assert result.candidates[0].permissions.can_publish is False


# ---------- widen ----------

def test_widen_run_doubles_region_radius_and_regenerates_candidates(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    region = _make_region(db_session, run, radius_m=1000)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    place_search = _FakePlaceSearch(places)
    place_facts = _FakePlaceFacts()

    flows.widen_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    db_session.refresh(region)
    assert region.radius_m == 2000  # WIDEN_FACTOR(2.0) 적용
    db_session.refresh(run)
    assert run.status == "done"
    assert service.list_candidates(db_session, str(run.id))[0].place_id == "p1"


def test_widen_run_without_regions_raises_not_ready(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    with pytest.raises(AppError) as exc_info:
        flows.widen_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts())
    assert exc_info.value.code == "NOT_READY"


# ---------- retry ----------

def test_retry_run_excludes_previous_unpublished_candidates_and_bumps_attempt(db_session):
    run = _make_run(db_session, status="done", attempt_no=1)
    _make_region(db_session, run, radius_m=1000)
    _make_candidate(db_session, run, place_id="old_place", published_pin_id=None)
    published = _make_candidate(db_session, run, place_id="published_place", published_pin_id=uuid.uuid4())

    new_places = [PlaceStub(place_id="old_place", lat=35.0005, lng=129.0005),
                  PlaceStub(place_id="fresh_place", lat=35.0006, lng=129.0006)]
    updated = flows.retry_run(
        db_session, run_id=str(run.id),
        place_search=_FakePlaceSearch(new_places), place_facts=_FakePlaceFacts(),
    )

    assert updated.attempt_no == 2
    remaining_place_ids = {c.place_id for c in service.list_candidates(db_session, str(run.id))}
    assert "old_place" not in remaining_place_ids  # 방금 제외목록에 들어간 곳은 재실행에서도 빠진다
    assert "fresh_place" in remaining_place_ids
    assert published.place_id in remaining_place_ids  # 게시된 후보는 그대로 유지


def test_retry_run_raises_retry_limit_when_exhausted(db_session):
    run = _make_run(db_session, status="done", attempt_no=5)
    _make_region(db_session, run)
    with pytest.raises(AppError) as exc_info:
        flows.retry_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts())
    assert exc_info.value.code == "RETRY_LIMIT"


def test_retry_run_checks_requesters_true_max_not_this_runs_own_attempt_no(db_session):
    """루트 수정(2026-09-23) — #31은 개인 단위 공유 카운터인데, retry_run이 이 run 자신의
    attempt_no만 봐서, 오래된(attempt_no가 낮은) run으로 retry를 걸면 상한을 우회할 수 있었다
    (Antigravity 검수로 발견). 같은 사람의 다른 run이 이미 상한(5)에 도달했으면, 더 오래된
    run(attempt_no=1)으로 retry를 시도해도 막혀야 한다."""
    old_run = _make_run(db_session, status="done", attempt_no=1, category="음식점")
    _make_region(db_session, old_run, radius_m=1000)
    _make_run(db_session, status="done", attempt_no=5, category="카페")  # 같은 사람의 최신 run

    with pytest.raises(AppError) as exc_info:
        flows.retry_run(
            db_session, run_id=str(old_run.id),
            place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts(),
        )
    assert exc_info.value.code == "RETRY_LIMIT"

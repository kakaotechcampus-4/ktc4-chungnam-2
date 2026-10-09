"""flows.py 전체 — publish_candidate(mentor-review-plan.md "검증" 절)와 #108 코어 파이프라인
(readiness/run 생성/evidence/지역확인/실행/결과/반경넓히기/재시도) 둘 다. 실제 PostgreSQL이
필요하다(db_session/test_engine, conftest.py 참고)."""

import threading
import uuid
from datetime import datetime, timezone

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
from recommend import constraints, core, flows, service
from recommend.models import Candidate, Exclusion, RecommendRun, Region
from places.schemas import FactLabel
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


def _react(db_session, pin, *, user_id, type="like", reason_text=None, reason_chip_ids=None):
    reaction = ReactionRow(pin_id=pin.id, user_id=user_id, type=type, reason_text=reason_text, reason_chip_ids=reason_chip_ids)
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

    def get_names(self, place_ids):
        return {p.place_id: f"이름-{p.place_id}" for p in self._places if p.place_id in set(place_ids)}


class _FakePlaceFacts:
    """{place_id: {fact_key: value}}를 place_facts 라벨(known)로 바꿔 돌려준다. 없는 장소·키는 라벨 없음 = unknown."""

    def __init__(self, facts_by_place=None):
        self._facts = facts_by_place or {}

    def get_facts(self, place_ids):
        return {
            pid: [FactLabel(key, value, "known") for key, value in self._facts.get(pid, {}).items()]
            for pid in place_ids
        }


def test_publish_candidate_inserts_ai_pin_links_candidate_and_records_event(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)

    pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )

    assert pin.kind == "AI추천"  # 반환은 pins.schemas.Pin(#114) — origin·place_id는 DB 행에서 확인한다
    row = db_session.execute(select(PinRow).where(PinRow.id == uuid.UUID(pin.id))).scalar_one()
    assert row.origin == "ai"
    assert row.place_id == candidate.place_id

    db_session.refresh(candidate)
    assert str(candidate.published_pin_id) == pin.id

    events = db_session.execute(select(EventLog).where(EventLog.map_id == run.map_id)).scalars().all()
    assert len(events) == 1
    assert events[0].type == "pin.published"  # docs/events.md — pins.api의 pin.created가 아니다


def test_publish_candidate_copies_candidate_checks_to_pin(db_session):
    """#124/#57 — 게시 시점에 candidate.checks가 pins.checks로 복사되고, 게시 뒤 유지된다
    (가드레일 5). pins.api.create_ai_pin(checks=...)/pins.schemas.Check 경계 검증까지 실제
    PostgreSQL로 왕복 확인한다."""
    run = _make_run(db_session)
    checks = [
        {"fact_key": "is_crowded_large", "label": "붐비는 대형 장소 아님", "passed": True,
         "confidence": "known", "needs_check": False},
        {"fact_key": "parking_available", "label": "주차 가능 확인 필요", "passed": True,
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


def test_publish_candidate_keeps_human_readable_check_labels(db_session):
    """#329 — build_check가 만든 사람 말 라벨("False"가 아님)이 게시된 핀에도 그대로 유지된다(가드레일 5)."""
    run = _make_run(db_session)
    built = [
        core.build_check("is_open", "pass", known=False, value=None, passes=True),
        core.build_check("is_crowded_large", "pass", known=True, value=False, passes=True),
        core.build_check("cuisine_korean", "pass", known=True, value=True, passes=True),
        core.build_check("quiet", "pass", known=False, value=None, passes=True),
    ]
    checks = [c.model_dump() for c in built]
    candidate = _make_candidate(db_session, run, checks=checks)

    pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )

    db_session.expire_all()
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    response = pins_api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_1", principal=principal,
    )
    assert [c.label for c in response.checks] == [
        "영업 여부 확인 필요", "붐비는 대형 장소 아님", "한식", "조용한 곳 확인 필요",
    ]


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


def test_publish_candidate_non_author_member_gets_404_ai_pin_private(db_session):
    """recommend.publish는 candidate.requested_by 본인만 가능(authz/policy.py AUTHOR_CONSTRAINED_ACTIONS).
    같은 지도 구성원이라도 본인이 아니면 남의 비공개 후보의 존재를 숨겨 404 AI_PIN_PRIVATE다(#255, 가드레일 1)."""
    run = _make_run(db_session, requested_by="user_1")
    candidate = _make_candidate(db_session, run)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_2",
            membership=_membership(run.map_id, "user_2"),  # 같은 지도 구성원이지만 run 요청자 본인이 아니다
        )
    assert exc_info.value.code == "AI_PIN_PRIVATE"


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
    409 PIN_DUPLICATE, 그리고 직전에 생긴 pins INSERT까지 함께 롤백돼 고아 행이
    안 남는지 확인한다(mentor-review-plan.md 레이스 2번)."""
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)
    db_session.commit()  # 기준선

    def _fake_link_published_pin(db, *, candidate_id, pin_id):
        raise AppError("PIN_DUPLICATE")

    monkeypatch.setattr(service, "link_published_pin", _fake_link_published_pin)

    with pytest.raises(AppError) as exc_info:
        flows.publish_candidate(
            db_session, candidate_id=str(candidate.id), requester_id="user_1",
            membership=_membership(run.map_id, "user_1"),
        )
    assert exc_info.value.code == "PIN_DUPLICATE"
    db_session.rollback()  # common/database.py get_db와 동일

    db_session.refresh(candidate)
    assert candidate.published_pin_id is None

    rows = db_session.execute(
        select(PinRow).where(PinRow.map_id == run.map_id, PinRow.place_id == candidate.place_id)
    ).scalars().all()
    assert rows == []  # 직전 pins INSERT까지 함께 롤백 — 고아 행 없음


def test_concurrent_publish_same_candidate_produces_exactly_one_pin(test_engine, monkeypatch):
    """동시에 두 요청을 보내 같은 후보를 게시하는 시나리오(세션 두 개로 흉내) — 하나는
    200(생성), 다른 하나는 409 PIN_DUPLICATE(PIN_DUPLICATE가 아니다). 최종적으로
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

def test_get_readiness_counts_opinion_pins_per_category(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2", "user_3"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")
    _react(db_session, pin, user_id="user_2", type="like")   # 같은 핀의 의견 둘 — 핀 1곳

    readiness = flows.get_readiness(db_session, map_id="map_1")

    assert readiness["음식점"] == {"ready": True, "answered_count": 1, "required_count": 1}
    assert readiness["카페"] == {"ready": False, "answered_count": 0, "required_count": 1}


def test_get_readiness_opens_for_a_solo_map_with_one_opinion_pin(db_session):
    _make_members(db_session, user_ids=["user_1"])   # 혼자 쓰는 지도
    pin = _make_pin(db_session, category="카페")
    _react(db_session, pin, user_id="user_1", type="like")

    readiness = flows.get_readiness(db_session, map_id="map_1")
    assert readiness["카페"] == {"ready": True, "answered_count": 1, "required_count": 1}


def test_get_readiness_ignores_opinions_of_non_members_and_deleted_pins(db_session):
    _make_members(db_session, user_ids=["user_1"])
    gone = _make_pin(db_session, category="음식점")
    gone.deleted_at = datetime.now(timezone.utc)
    _react(db_session, gone, user_id="user_1", type="like")        # 삭제된 핀
    alive = _make_pin(db_session, category="음식점")
    _react(db_session, alive, user_id="left_user", type="against", reason_text="멀어요")   # 나간 사람

    readiness = flows.get_readiness(db_session, map_id="map_1")
    assert readiness["음식점"]["answered_count"] == 0 and readiness["음식점"]["ready"] is False


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


def _no_plan_call(raw):
    raise AssertionError(f"칩만 있으면 ②를 부르지 않는다: {raw}")


def test_create_run_turns_each_chip_into_its_own_evidence_line_without_calling_the_model(db_session, monkeypatch):
    """#412 — 칩만 남긴 🚫는 ② 호출 없이 칩 하나당 줄 하나. 키·방향은 칩 표 그대로, 배지 required, 글은 label."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_chip_ids=["food_spicy", "food_cramped"])
    monkeypatch.setattr(flows.llm_service, "plan_evidence", _no_plan_call)

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    lines = service.list_evidence(db_session, str(run.id))
    assert [(l.text, l.chip_id, l.fact_key, l.wants, l.badge, l.source, l.author_id) for l in lines] == [
        ("매워요", "food_spicy", "spicy_focused", False, "required", "reaction", "user_1"),
        ("좁아요", "food_cramped", "spacious", True, "required", "reaction", "user_1"),
    ]


def test_create_run_sends_only_the_written_text_to_the_model_and_keeps_the_chips(db_session, monkeypatch):
    """#412 — 글과 칩을 함께 남기면 둘 다 근거다. ②에는 글만 가고, 반응마다 글 줄 다음에 칩 줄이 붙는다."""
    _make_members(db_session, user_ids=["user_1", "user_2"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="한식 말고", reason_chip_ids=["food_oily"])
    _react(db_session, pin, user_id="user_2", type="against", reason_chip_ids=["common_far"])
    sent = []
    real_plan = flows.llm_service.plan_evidence

    def spy_plan(raw):
        sent.append([line["text"] for line in raw])
        return real_plan(raw)

    monkeypatch.setattr(flows.llm_service, "plan_evidence", spy_plan)

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert sent == [["한식 말고"]]
    lines = service.list_evidence(db_session, str(run.id))
    by_author = sorted((l.author_id, l.text, l.chip_id, l.fact_key, l.wants, l.badge) for l in lines)
    assert by_author == [
        ("user_1", "느끼해요", "food_oily", "oily_focused", False, "required"),
        ("user_1", "한식 말고", None, None, None, "required"),   # dev 패스스루 ②라 키는 비어 있다
        ("user_2", "너무 멀어요", "common_far", None, None, "required"),   # 키 없는 공통 칩도 줄은 있다(#255)
    ]


def test_create_run_demotes_wanted_cuisine_from_a_against_reason_to_preferred(db_session, monkeypatch):
    """#422 — "한식 말고 고기 먹고 싶어요"(🚫): 한식 피함은 required, 고기구이 원함은 preferred로 저장된다."""
    from llm.schemas import EvidenceLine
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="한식 말고 고기 먹고 싶어요")
    text = "한식 말고 고기 먹고 싶어요"
    monkeypatch.setattr(flows.llm_service, "plan_evidence", lambda raw: [[
        EvidenceLine(author_id="user_1", source="reaction", text=text, badge="required", fact_key="cuisine_korean", wants=False),
        EvidenceLine(author_id="user_1", source="reaction", text=text, badge="required", fact_key="cuisine_bbq", wants=True),
    ]])

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    lines = service.list_evidence(db_session, str(run.id))
    assert [(l.fact_key, l.wants, l.badge) for l in lines] == [
        ("cuisine_korean", False, "required"),
        ("cuisine_bbq", True, "preferred"),
    ]
    assert flows._active_soft_requirements(db_session, run) == [("cuisine_korean", False)]


def test_create_run_keeps_a_legacy_chip_value_as_text_without_key(db_session, monkeypatch):
    """#412 — #312 전에 이름 그대로 저장된 옛 값은 그 값을 글로 쓰고 키·방향 없이 둔다(② 호출 없음)."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_chip_ids=["매워요"])
    monkeypatch.setattr(flows.llm_service, "plan_evidence", _no_plan_call)

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    [line] = service.list_evidence(db_session, str(run.id))
    assert (line.text, line.chip_id, line.fact_key, line.wants, line.badge) == ("매워요", "매워요", None, None, "required")


def test_reaction_left_with_the_retired_shellfish_chip_filters_nothing(db_session, monkeypatch):
    """#425 — 「갑각류 알러지가 있어요」 칩은 뺐다. 그 전에 이 칩으로 남긴 반응은 근거 줄로만 남고 아무것도 켜지 않는다
    (알러지는 서비스가 판단하지 않는다)."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_chip_ids=["food_shellfish"])
    monkeypatch.setattr(flows.llm_service, "plan_evidence", _no_plan_call)

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    [line] = service.list_evidence(db_session, str(run.id))
    assert (line.chip_id, line.badge) == ("food_shellfish", "required")
    assert flows._active_hard_fact_keys(db_session, run) == []
    assert flows._active_soft_requirements(db_session, run) == []


def test_soft_chip_becomes_a_directed_requirement(db_session, monkeypatch):
    """#412 — 「좁아요」는 넓은 곳을 원한다(spacious, wants=true). required라 #231 방향 실격으로 켜진다."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_chip_ids=["food_cramped", "food_spicy"])
    monkeypatch.setattr(flows.llm_service, "plan_evidence", _no_plan_call)

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert flows._active_soft_requirements(db_session, run) == [("spacious", True), ("spicy_focused", False)]


_KEYED_CHIP_IDS = {
    "음식점": ["food_spicy", "food_oily", "food_wait", "food_cramped"],   # food_shellfish는 #425에서 뺐다
    "카페": ["cafe_crowded", "cafe_noisy", "cafe_seat"],
    "관광지": ["sight_inaccessible", "sight_noisy"],
}
# 키 없는 칩 — 「공통」 칩, 그리고 #423에서 키를 뗀 가격 칩(칩은 남는다)
_KEYLESS_CHIP_IDS = {
    "음식점": ["food_expensive"],
    "카페": ["cafe_expensive"],
    "관광지": ["sight_expensive"],
}


@pytest.mark.parametrize("category", list(_KEYED_CHIP_IDS))
def test_every_chip_key_is_one_the_filter_knows(db_session, category):
    """#412 — 칩 줄은 ②를 거치지 않아 모델 스키마 검증을 안 받는다. 칩 표(docs/constraints.md)의 키가 그 카테고리의
    레지스트리에 있고 방향이 있어야 실격·선호가 켜진다. 「공통」 칩과 가격 칩(#423)은 키·방향이 둘 다 없다."""
    pin = _make_pin(db_session, category=category)
    _react(db_session, pin, user_id="user_1", type="against",
           reason_chip_ids=[*_KEYED_CHIP_IDS[category], *_KEYLESS_CHIP_IDS[category], "common_not_my_taste", "common_far"])

    [reaction] = pins_api.list_reasoned_reactions(db_session, map_id="map_1", category=category)

    applicable = {*constraints.hard_fact_keys_for(category), *constraints.soft_fact_keys_for(category)}
    keyed = [chip for chip in reaction["chips"] if chip["fact_key"] is not None]
    assert [chip["chip_id"] for chip in keyed] == _KEYED_CHIP_IDS[category]
    assert all(chip["fact_key"] in applicable and chip["wants"] is not None for chip in keyed)
    assert [(c["chip_id"], c["wants"]) for c in reaction["chips"] if c["fact_key"] is None] == [
        *((chip_id, None) for chip_id in _KEYLESS_CHIP_IDS[category]), ("common_not_my_taste", None), ("common_far", None),
    ]


def _make_live_pin(db_session, *, map_id="map_1", category="음식점", kakao_place_id="kakao:live1", created_by="user_1"):
    """실시간 핀(#382) — place_id·geom이 없다."""
    pin = PinRow(
        id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct", source="live",
        kakao_place_id=kakao_place_id, search_query="q", visibility="public", created_by=created_by,
    )
    db_session.add(pin)
    db_session.flush()
    return pin


def test_create_run_skips_live_pins_for_the_search_circle_but_keeps_their_reasons(db_session):
    """#386 — 좌표 없는 live 핀은 기준 원에서 빠지고, 그 핀에 남긴 사유는 근거 줄로 그대로 쓰인다."""
    _make_members(db_session, user_ids=["user_1"])
    db_pin = _make_pin(db_session, category="음식점", lat=35.2, lng=129.3)
    live_pin = _make_live_pin(db_session)
    _react(db_session, live_pin, user_id="user_1", type="against", reason_text="조개 알러지")

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert [line.text for line in service.list_evidence(db_session, str(run.id))] == ["조개 알러지"]
    (region,) = service.list_regions(db_session, str(run.id))
    assert (region.center_lat, region.center_lng) == (pytest.approx(35.2), pytest.approx(129.3))
    assert len(region.anchor_points) == 1 and db_pin is not None


def test_readiness_counts_a_live_pin_with_an_opinion(db_session):
    _make_members(db_session, user_ids=["user_1"])
    live_pin = _make_live_pin(db_session, category="카페")
    _react(db_session, live_pin, user_id="user_1", type="like")

    assert flows.get_readiness(db_session, map_id="map_1")["카페"] == {
        "ready": True, "answered_count": 1, "required_count": 1,
    }


def test_create_run_with_only_live_pins_has_no_anchor_so_not_ready(db_session):
    """live 핀만 있으면 기준 원을 만들 좌표가 없다 — 준비 판정은 통과해도 run 생성은 409 NOT_READY(스펙 갭, 루트 보고)."""
    _make_members(db_session, user_ids=["user_1"])
    live_pin = _make_live_pin(db_session)
    _react(db_session, live_pin, user_id="user_1", type="like")

    with pytest.raises(AppError) as exc_info:
        flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")
    assert exc_info.value.code == "NOT_READY"


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
    # anchor_points(#112) — 이 헬퍼로 직접 만드는 region은 create_run을 거치지 않아 실제 핀
    # 좌표를 모른다. 중심 좌표 자체를 기준 핀 1개로 대신한다 — select_top_candidates의 거리
    # tie-break가 최소한 동작은 하도록(값 자체의 정확성보다 "기준 핀 없음" 에러를 피하는 게 목적).
    region = Region(
        run_id=run.id, signature="sig", label=label, center_lat=center_lat, center_lng=center_lng,
        radius_m=radius_m, anchor_points=[[center_lat, center_lng]], confirmed=True,
    )
    db_session.add(region)
    db_session.flush()
    return region


def test_execute_run_full_funnel_removes_out_of_radius_disqualified_and_excluded(db_session):
    run = _make_run(db_session, status="collecting_evidence", category="카페")
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "너무 붐벼요",
         "badge": "required", "fact_key": "is_crowded_large"},
    ])
    service.add_exclusions(
        db_session, map_id="map_1", category="카페", place_ids=["excluded_place"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )

    places = [
        PlaceStub(place_id="ok_place", lat=35.0005, lng=129.0005),       # 반경 안, 실격 아님(known) → 통과
        PlaceStub(place_id="crowded_place", lat=35.0005, lng=129.0006),  # 반경 안, 붐비는 대형(known) → 실격
        PlaceStub(place_id="far_place", lat=40.0, lng=135.0),            # 반경 밖 → 제거
        PlaceStub(place_id="excluded_place", lat=35.0004, lng=129.0004),  # 반경 안, 실격 아님(known), 제외목록 → 제거
    ]
    place_search = _FakePlaceSearch(places)
    # known 값을 명시해 실격이 "붐빔" 하나로만 갈리게 한다. facts에 없는 far_place는 반경 필터에서 이미 빠져
    # 라벨링 자체를 안 받는다.
    place_facts = _FakePlaceFacts({
        "ok_place": {"is_crowded_large": False},
        "crowded_place": {"is_crowded_large": True},
        "excluded_place": {"is_crowded_large": False},
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


def _dismissal_setup(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)
    disliked = _make_pin(db_session, lat=35.0005, lng=129.0005)
    _react(db_session, disliked, user_id="user_1", type="against", reason_text="싫어요")
    places = [
        PlaceStub(place_id=disliked.place_id, lat=35.0005, lng=129.0005),
        PlaceStub(place_id="new_place", lat=35.0006, lng=129.0006),
    ]
    return run, disliked, _FakePlaceSearch(places), _FakePlaceFacts({disliked.place_id: {}, "new_place": {}})


def test_execute_run_excludes_place_the_requester_disliked_even_after_pin_is_deleted(db_session):
    """가드레일 6(#119) — 핀이 소프트 삭제되면 list_place_ids_on_map에서 빠져 거절한 장소가 다시
    추천됐다. 요청자의 🚫는 exclusions(dismissed)로 남아 삭제 뒤에도 제외된다."""
    from datetime import datetime, timezone

    run, disliked, place_search, place_facts = _dismissal_setup(db_session)
    disliked.deleted_at = datetime.now(timezone.utc)
    db_session.flush()

    updated = flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    assert [c.place_id for c in service.list_candidates(db_session, str(run.id))] == ["new_place"]
    assert {entry["label"]: entry["removed_count"] for entry in updated.last_funnel}["이미 제안·거절됨"] == 1
    rows = db_session.execute(select(Exclusion.place_id, Exclusion.reason)).all()
    assert rows == [(disliked.place_id, "dismissed")]


def test_execute_run_does_not_exclude_place_only_another_member_disliked(db_session):
    """다른 구성원의 🚫는 요청자의 제외목록이 아니다(근거 줄을 거쳐 실격 경로로 간다)."""
    from datetime import datetime, timezone

    run, disliked, place_search, place_facts = _dismissal_setup(db_session)
    db_session.execute(delete(ReactionRow))
    _react(db_session, disliked, user_id="user_2", type="against", reason_text="싫어요")
    disliked.deleted_at = datetime.now(timezone.utc)
    db_session.flush()

    flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    assert {c.place_id for c in service.list_candidates(db_session, str(run.id))} == {disliked.place_id, "new_place"}
    assert db_session.execute(select(func.count()).select_from(Exclusion)).scalar_one() == 0


def test_execute_run_twice_with_dismissal_is_idempotent(db_session):
    run, disliked, place_search, place_facts = _dismissal_setup(db_session)
    flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)
    flows.execute_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)
    assert db_session.execute(select(func.count()).select_from(Exclusion)).scalar_one() == 1


def test_execute_run_allergy_reason_filters_nothing(db_session):
    """#425 — 알러지 같은 안전 조건은 서비스가 판단하지 않는다. 알러지 사유는 키 없는 근거 줄이라 라벨이
    모름인 곳도 빼지 않는다(전에는 안전 조건이라 모름도 빼서 어느 동네든 0곳이었다). 갑각류 체크도 붙지 않는다."""
    candidates, funnel = _execute_with_lines(
        db_session, [_line("user_1", "required", None, None, text="갑각류 알러지가 있어요")], {"unknown_place": {}},
    )
    assert set(candidates) == {"unknown_place"} and funnel["실격 조건 제거"] == 0
    assert all(c["fact_key"] != "contains_shellfish" for c in candidates["unknown_place"].checks)


def test_execute_run_keeps_candidate_whose_unwanted_soft_label_is_false(db_session):
    """#208 — 아무도 조용한 곳을 원하지 않았어도 quiet=False 장소가 실격되던 버그. soft 라벨은
    실격 판정에 쓰이지 않으므로 후보에 남고, hard is_crowded_large=True인 장소만 여전히 실격이다."""
    run = _make_run(db_session, status="collecting_evidence", category="카페")
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "너무 붐벼요",
         "badge": "required", "fact_key": "is_crowded_large"},
    ])
    places = [
        PlaceStub(place_id="noisy_place", lat=35.0005, lng=129.0005),
        PlaceStub(place_id="crowded_place", lat=35.0005, lng=129.0006),
    ]
    place_facts = _FakePlaceFacts({
        "noisy_place": {"is_crowded_large": False, "quiet": False, "comfortable_seat": False},
        "crowded_place": {"is_crowded_large": True, "quiet": False},
    })

    updated = flows.execute_run(
        db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=place_facts,
    )

    assert [c.place_id for c in service.list_candidates(db_session, str(run.id))] == ["noisy_place"]
    assert {e["label"]: e["removed_count"] for e in updated.last_funnel}["실격 조건 제거"] == 1


def test_execute_run_keeps_restaurants_whose_cuisine_labels_are_mostly_false(db_session):
    """#171 + #208 — cuisine_* 10개는 한 곳당 9개가 거짓이다. 아무도 원하지 않았으니 전원 후보에 남고,
    점수 영향도 없다(전원 0점). 음식점 카테고리에는 음식점 선호 키만 체크로 붙는다."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    cuisines = [
        "cuisine_korean", "cuisine_chinese", "cuisine_japanese", "cuisine_western", "cuisine_bunsik",
        "cuisine_chicken_pub", "cuisine_bbq", "cuisine_foreign", "cuisine_raw_fish", "cuisine_buffet",
    ]
    places = [PlaceStub(place_id=f"r{i}", lat=35.0005 + i * 0.0001, lng=129.0005) for i in range(len(cuisines))]
    place_facts = _FakePlaceFacts({
        f"r{i}": {**{key: (key == cuisines[i]) for key in cuisines}, "franchise": False, "spacious": False}
        for i in range(len(cuisines))
    })

    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=place_facts)

    candidates = service.list_candidates(db_session, str(run.id))
    assert len(candidates) == 3  # 상위 3곳 선정까지 가고, 실격으로 줄지 않는다
    keys = {check["fact_key"] for check in candidates[0].checks}
    assert not keys & set(cuisines)  # 아무도 말하지 않은 known(거짓 9개) cuisine_*은 응답 checks에 없다
    assert "quiet" not in keys and "winter_spot" not in keys


def _run_with_wanted_and_unwanted_soft_keys(db_session):
    """음식점 run — 선호 사유 wait_short(unknown), ♥ 핀 기준 cuisine_japanese. 음식점에는 라벨 실격 키가 없다(#425).
    라벨: franchise 거짓 known, cuisine_japanese 참 known, 나머지 soft는 unknown.
    ♥ 핀 기준은 음식점에서 ♥ 한 곳으로도 쓰이는 업태 키다(#414 — 주차 같은 편의 키는 ♥에서 쓰지 않는다)."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_2", "source": "reaction", "text": "대기 짧았으면", "badge": "preferred", "fact_key": "wait_short"},
    ])
    liked = _make_pin(db_session, lat=35.0008, lng=129.0008)
    _react(db_session, liked, user_id="user_1", type="like")
    places = [PlaceStub(place_id="cand", lat=35.0005, lng=129.0005)]
    # ♥ 핀의 라벨은 places(place_facts)에서 읽는다(#247) — 핀에 복사된 checks가 아니다.
    facts = _FakePlaceFacts({
        "cand": {"franchise": False, "cuisine_japanese": True},
        liked.place_id: {"cuisine_japanese": True},
    })
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=facts)
    [candidate] = service.list_candidates(db_session, str(run.id))
    return run, candidate


def test_execute_run_checks_omit_unwanted_unknown_soft_keys(db_session):
    """#216 — 아무도 원하지 않았고 unknown인 soft 키(pet_friendly 등)는 저장되는 checks에 없다(known인 franchise도). 원한 키는
    known이든 unknown이든 남고(unknown은 needs_check), hard 체크는 그대로다."""
    _run, candidate = _run_with_wanted_and_unwanted_soft_keys(db_session)
    by_key = {c["fact_key"]: c for c in candidate.checks}

    assert "pet_friendly" not in by_key and "vegetarian_friendly" not in by_key  # 원하지 않은 unknown
    assert "franchise" not in by_key  # 원하지 않은 known(거짓)도 싣지 않는다
    assert by_key["wait_short"]["needs_check"] is True and by_key["wait_short"]["confidence"] == "unknown"  # 활성 근거 줄
    assert by_key["cuisine_japanese"]["confidence"] == "known"  # ♥ 핀 기준(known)
    assert "is_open" in by_key  # hard(코드 판정) 그대로


def test_execute_run_unwanted_unknown_soft_checks_still_feed_scoring(db_session):
    """점수 입력은 전체 soft 체크다 — 저장에서 빠져도 ♥ 핀 기준(cuisine_japanese)이 점수에 쓰인다."""
    _run, candidate = _run_with_wanted_and_unwanted_soft_keys(db_session)
    assert candidate.member_fulfillment["total"] >= 1 and candidate.member_fulfillment["satisfied"] >= 1
    assert "일식" in candidate.reason


def test_publish_candidate_pin_checks_follow_the_same_filter(db_session):
    """게시(pins 복사)는 candidate.checks 그대로라 같은 기준이다 — 원하지 않은 unknown soft는 핀에도 없다."""
    run, candidate = _run_with_wanted_and_unwanted_soft_keys(db_session)
    pin = flows.publish_candidate(
        db_session, candidate_id=str(candidate.id), requester_id="user_1",
        membership=_membership(run.map_id, "user_1"),
    )
    db_session.expire_all()
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    response = pins_api.get_pin_response_for_viewer(
        db_session, pin_id=str(pin.id), viewer_id="user_1", principal=principal,
    )
    pin_keys = [c.fact_key for c in response.checks]
    assert pin_keys == [c["fact_key"] for c in candidate.checks]
    assert "pet_friendly" not in pin_keys and "wait_short" in pin_keys


def test_create_run_leaves_no_run_row_when_planning_fails(db_session, monkeypatch):
    """#208 — 모델 호출(②)을 INSERT보다 먼저 하므로 실패하면 run 행이 남지 않는다."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")

    def boom(_lines):
        raise RuntimeError("model down")

    monkeypatch.setattr(flows.llm_service, "plan_evidence", boom)
    with pytest.raises(RuntimeError):
        flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert db_session.execute(select(func.count()).select_from(RecommendRun)).scalar_one() == 0


def test_create_run_rechecks_retry_limit_after_planning(db_session, monkeypatch):
    """#208 — LLM 대기 중 동시 요청이 상한(5)에 도달시키면 INSERT 직전 재검사가 429로 막는다."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")
    real_plan = flows.llm_service.plan_evidence

    def plan_while_other_request_hits_limit(lines):
        _make_run(db_session, map_id="map_1", requested_by="user_1", category="카페", attempt_no=5)
        return real_plan(lines)

    monkeypatch.setattr(flows.llm_service, "plan_evidence", plan_while_other_request_hits_limit)
    with pytest.raises(AppError) as exc_info:
        flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")
    assert exc_info.value.code == "RETRY_LIMIT"
    assert db_session.execute(
        select(func.count()).select_from(RecommendRun).where(RecommendRun.category == "음식점")
    ).scalar_one() == 0


def test_execute_run_with_no_candidates_then_get_result_is_no_results(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run)
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts())

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    with pytest.raises(AppError) as exc_info:
        flows.get_result(db_session, run_id=str(run.id), principal=principal, place_search=_FakePlaceSearch([]))
    assert exc_info.value.code == "NO_RESULTS"
    assert "funnel" in exc_info.value.detail


def test_get_result_marks_can_publish_true_only_for_run_author(db_session):
    run = _make_run(db_session, status="collecting_evidence", requested_by="user_1")
    _make_region(db_session, run)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts())

    author = Principal(user_id="user_1", map_id="map_1", role="member")
    result = flows.get_result(db_session, run_id=str(run.id), principal=author, place_search=_FakePlaceSearch([]))
    assert result.candidates[0].permissions.can_publish is True

    stranger = Principal(user_id="user_2", map_id="map_1", role="member")
    result2 = flows.get_result(db_session, run_id=str(run.id), principal=stranger, place_search=_FakePlaceSearch([]))
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

    result = flows.get_result(db_session, run_id=str(run.id), principal=author, place_search=_FakePlaceSearch([]))
    assert result.candidates[0].visibility == "published"
    assert result.candidates[0].permissions.can_publish is False


# ---------- widen ----------

def test_widen_run_adds_five_walk_minutes_and_regenerates_candidates(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    region = _make_region(db_session, run, radius_m=15 * 80)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    place_search = _FakePlaceSearch(places)
    place_facts = _FakePlaceFacts()

    returned = flows.widen_run(db_session, run_id=str(run.id), place_search=place_search, place_facts=place_facts)

    db_session.refresh(region)
    assert region.radius_m == 20 * 80  # 15분 → 20분(+5분)
    db_session.refresh(run)
    assert returned is run
    assert run.default_radius_walk_min == 20
    assert run.status == "done"
    assert service.list_candidates(db_session, str(run.id))[0].place_id == "p1"


def test_widen_run_steps_to_limit_then_raises_widen_limit_without_changing_anything(db_session):
    run = _make_run(db_session, status="done")
    region = _make_region(db_session, run, radius_m=15 * 80)
    kwargs = {"place_search": _FakePlaceSearch([]), "place_facts": _FakePlaceFacts()}

    for expected in (20, 25, 30):
        flows.widen_run(db_session, run_id=str(run.id), **kwargs)
        assert run.default_radius_walk_min == expected

    with pytest.raises(AppError) as exc_info:
        flows.widen_run(db_session, run_id=str(run.id), **kwargs)
    assert exc_info.value.code == "WIDEN_LIMIT"
    db_session.refresh(region)
    assert region.radius_m == 30 * 80  # 상한을 넘겨 완화하지 않는다(가드레일 4)
    assert run.default_radius_walk_min == 30


def test_widen_run_without_regions_raises_not_ready(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    with pytest.raises(AppError) as exc_info:
        flows.widen_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts())
    assert exc_info.value.code == "NOT_READY"


# ---------- #158 Candidate 가드레일5 필드 ----------

def test_execute_run_fills_reason_member_fulfillment_and_place_source(db_session):
    run = _make_run(db_session, status="collecting_evidence", category="카페")
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "너무 붐벼요", "badge": "required", "fact_key": "is_crowded_large"},
        {"author_id": "user_2", "source": "reaction", "text": "조용했으면", "badge": "preferred", "fact_key": "quiet", "wants": True},
    ])
    source = {"provider": "kakao", "url": "https://place.map.kakao.com/1"}
    places = [
        PlaceStub(place_id="sourced", lat=35.0005, lng=129.0005, source=source),
        PlaceStub(place_id="bare", lat=35.0006, lng=129.0006),
    ]
    facts = _FakePlaceFacts({
        "sourced": {"is_crowded_large": False, "quiet": True},
        "bare": {"is_crowded_large": False},
    })

    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=facts)

    by_place = {c.place_id: c for c in service.list_candidates(db_session, str(run.id))}
    sourced, bare = by_place["sourced"], by_place["bare"]
    assert sourced.reason == "실격 조건 통과: 붐비는 대형 장소 아님 · 선호 충족: 조용함 (1/1명)"
    # user_1은 실격 사유(너무 붐벼요)를 냈고 후보가 통과했으니 충족(#255). 이유 문장의 (1/1명)은 선호 구성원만 센다.
    assert sourced.member_fulfillment == {"satisfied": 2, "total": 2, "by_member": [
        {"user_id": "user_1", "satisfied": True}, {"user_id": "user_2", "satisfied": True},
    ]}
    assert sourced.place_source == source
    # 조용함을 모르는 후보 — 구성원은 집계 대상이지만 충족으로 세지 않고, 안 본 것을 이유로 들지 않는다.
    assert bare.reason == "실격 조건 통과: 붐비는 대형 장소 아님"
    assert bare.member_fulfillment == {"satisfied": 1, "total": 2, "by_member": [
        {"user_id": "user_1", "satisfied": True}, {"user_id": "user_2", "satisfied": False},
    ]}
    assert bare.place_source is None  # 출처를 못 얻으면 지어내지 않는다


def test_get_result_exposes_reason_member_fulfillment_and_place_source(db_session):
    run = _make_run(db_session, status="done")
    _make_region(db_session, run)
    _make_candidate(
        db_session, run, reason="이유", member_fulfillment={"satisfied": 1, "total": 2, "by_member": []},
        place_source={"provider": "naver"},
    )
    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    candidate = flows.get_result(db_session, run_id=str(run.id), principal=principal, place_search=_FakePlaceSearch([])).candidates[0]
    assert candidate.reason == "이유"
    assert candidate.member_fulfillment.satisfied == 1 and candidate.member_fulfillment.total == 2
    assert candidate.place_source.provider == "naver"


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


# ---------- #231 — 사유의 방향(wants) ----------

def _line(author, badge, fact_key, wants, text="사유"):
    return {"author_id": author, "source": "reaction", "text": text, "badge": badge, "fact_key": fact_key, "wants": wants}


def _execute_with_lines(db_session, lines, facts_by_place, *, category="음식점"):
    """wants를 직접 심은 근거 줄로 파이프라인을 돌린다(②의 wants 생성은 llm 쪽 이슈)."""
    run = _make_run(db_session, status="collecting_evidence", category=category)
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=lines)
    places = [PlaceStub(place_id=pid, lat=35.0005, lng=129.0005) for pid in facts_by_place]
    flows.execute_run(
        db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places),
        place_facts=_FakePlaceFacts(facts_by_place),
    )
    candidates = {c.place_id: c for c in service.list_candidates(db_session, str(run.id))}
    funnel = {entry["label"]: entry["removed_count"] for entry in run.last_funnel}
    return candidates, funnel


def test_required_wants_false_removes_places_whose_label_is_true(db_session):
    """"한식 말고"(required, wants=false) — 한식 참인 후보는 제거되고 거짓이면 남는다. 깔때기에 세어진다."""
    candidates, funnel = _execute_with_lines(
        db_session, [_line("user_1", "required", "cuisine_korean", False)],
        {"korean": {"cuisine_korean": True}, "other": {"cuisine_korean": False}},
    )
    assert set(candidates) == {"other"}
    assert funnel["실격 조건 제거"] == 1


def test_required_wants_false_unknown_label_passes_with_needs_check(db_session):
    candidates, funnel = _execute_with_lines(
        db_session, [_line("user_1", "required", "cuisine_korean", False)], {"unknown_place": {}},
    )
    check = next(c for c in candidates["unknown_place"].checks if c["fact_key"] == "cuisine_korean")
    assert check["confidence"] == "unknown" and check["needs_check"] is True and check["passed"] is True
    assert funnel["실격 조건 제거"] == 0


def test_required_wants_true_is_the_inverse(db_session):
    """"조용한 곳이어야 해"(required, wants=true) — 라벨 거짓이면 실격, 참이면 통과, 모름은 통과 + needs_check."""
    candidates, funnel = _execute_with_lines(
        db_session, [_line("user_1", "required", "quiet", True)],
        {"quiet": {"quiet": True}, "noisy": {"quiet": False}, "unknown_place": {}},
    )
    assert set(candidates) == {"quiet", "unknown_place"}
    assert funnel["실격 조건 제거"] == 1
    check = next(c for c in candidates["unknown_place"].checks if c["fact_key"] == "quiet")
    assert check["needs_check"] is True


def test_required_soft_with_null_wants_has_no_effect(db_session):
    """방향이 없던 시절 근거 줄(wants=NULL)은 이전과 같다 — 라벨이 참이어도 실격이 아니다."""
    candidates, funnel = _execute_with_lines(
        db_session, [_line("user_1", "required", "cuisine_korean", None)], {"korean": {"cuisine_korean": True}},
    )
    assert set(candidates) == {"korean"} and funnel["실격 조건 제거"] == 0


def test_hard_key_required_disqualifies_only_known_true_whatever_wants_says(db_session):
    """hard 키는 방향이 고정이라("있으면 실격") required면 wants와 무관하게 켜진다(constraints.md "사유의 방향").
    unknown_policy=pass라 모름은 통과 + needs_check다(#425 뒤로 exclude 키는 없다)."""
    facts = {"crowded": {"is_crowded_large": True}, "calm": {"is_crowded_large": False}, "unknown_place": {}}
    for wants in (False, None, True):
        candidates, funnel = _execute_with_lines(
            db_session, [_line("user_1", "required", "is_crowded_large", wants)], facts, category="카페",
        )
        assert set(candidates) == {"calm", "unknown_place"} and funnel["실격 조건 제거"] == 1, wants
        check = next(c for c in candidates["unknown_place"].checks if c["fact_key"] == "is_crowded_large")
        assert check["passed"] is True and check["needs_check"] is True, wants


def test_spicy_and_oily_required_wants_false_disqualify_only_known_true_and_unknown_passes(db_session):
    """#378 — 매운맛·기름진 메뉴는 취향 키: 🚫(required, wants=false)는 라벨이 참인 곳만 실격, 모름은 통과 + needs_check."""
    for key in ("spicy_focused", "oily_focused"):
        candidates, funnel = _execute_with_lines(
            db_session, [_line("user_1", "required", key, False)],
            {"hot": {key: True}, "mild": {key: False}, "unknown_place": {}},
        )
        assert set(candidates) == {"mild", "unknown_place"} and funnel["실격 조건 제거"] == 1, key
        check = next(c for c in candidates["unknown_place"].checks if c["fact_key"] == key)
        assert check["confidence"] == "unknown" and check["passed"] is True and check["needs_check"] is True


def test_spicy_and_oily_preferred_wants_false_is_a_penalty_not_a_disqualifier(db_session):
    """#378 — ♥·「+」(preferred, wants=false)는 실격이 아니라 감점: 매운 곳도 남되 순위가 아래다."""
    for key in ("spicy_focused", "oily_focused"):
        candidates, funnel = _execute_with_lines(
            db_session, [_line("user_1", "preferred", key, False)],
            {"hot": {key: True}, "mild": {key: False}, "unknown_place": {}},
        )
        assert set(candidates) == {"hot", "mild", "unknown_place"} and funnel["실격 조건 제거"] == 0, key
        assert candidates["hot"].rank > candidates["mild"].rank, key


def test_price_reason_is_a_keyless_line_and_a_leftover_price_label_is_ignored(db_session):
    """#423 — "비싸요"는 키 없는 근거 줄이라 아무것도 거르지 않는다. 시연 DB에 price_bucket 라벨 행이 남아 있어도
    레지스트리에 없는 키라 체크로 붙지 않는다(관광지 「입장료가 비싸요」도 같다)."""
    for category, text in (("음식점", "비싸요"), ("관광지", "입장료가 비싸요")):
        candidates, funnel = _execute_with_lines(
            db_session, [_line("user_1", "required", None, None, text=text)], {"p": {"price_bucket": "high"}},
            category=category,
        )
        assert set(candidates) == {"p"} and funnel["실격 조건 제거"] == 0, category
        assert all(c["fact_key"] != "price_bucket" for c in candidates["p"].checks), category


def test_hard_key_preferred_and_reference_never_disqualify(db_session):
    """♥·「+」로 남긴 hard 키 사유는 실격을 켜지 않는다. 배지와 무관하게 실격이던 안전 조건 규칙(D11, #254)은
    #425에서 안전 조건 키와 함께 없앴다."""
    facts = {"crowded": {"is_crowded_large": True}, "calm": {"is_crowded_large": False}, "unknown_place": {}}
    for badge in ("preferred", "reference"):
        for wants in (False, True, None):
            candidates, funnel = _execute_with_lines(
                db_session, [_line("user_1", badge, "is_crowded_large", wants)], facts, category="카페",
            )
            assert set(candidates) == set(facts) and funnel["실격 조건 제거"] == 0, (badge, wants)


def test_inactive_hard_reason_is_not_applied(db_session):
    run = _make_run(db_session, status="collecting_evidence", category="카페")
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {**_line("user_1", "required", "is_crowded_large", False), "is_active": False},
    ])
    assert flows._active_hard_fact_keys(db_session, run) == []


def test_plus_manual_line_goes_through_plan_evidence_and_keeps_reference_badge(db_session, monkeypatch):
    """#254 — 「+」로 추가한 줄도 ②로 보내 fact_key·wants를 붙인다. 배지는 reference."""
    from llm.schemas import EvidenceLine as PlannedLine

    sent = []

    def planner(raw):
        sent.extend(raw)
        return [[PlannedLine(**{**r, "fact_key": "spicy_focused", "wants": False})] for r in raw]

    monkeypatch.setattr(flows.llm_service, "plan_evidence", lambda raw: planner(raw))
    run = _make_run(db_session, status="collecting_evidence")
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")

    flows.patch_evidence(db_session, run_id=str(run.id), principal=principal, toggles=[], adds=["매운 건 못 먹어요"])

    assert [r["source"] for r in sent] == ["manual"]
    [line] = service.list_evidence(db_session, str(run.id))
    assert (line.badge, line.fact_key, line.wants) == ("reference", "spicy_focused", False)
    assert flows._active_soft_requirements(db_session, run) == []   # reference는 실격을 켜지 않는다


def test_plus_manual_line_planner_failure_leaves_no_line(db_session, monkeypatch):
    def boom(raw):
        raise RuntimeError("②가 죽었다")

    monkeypatch.setattr(flows.llm_service, "plan_evidence", boom)
    run = _make_run(db_session, status="collecting_evidence")
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    with pytest.raises(RuntimeError):
        flows.patch_evidence(db_session, run_id=str(run.id), principal=principal, toggles=[], adds=["x"])
    assert service.list_evidence(db_session, str(run.id)) == []


# ---------- #419 — 사유 글 하나에 조건이 여럿이면 근거 줄을 나눈다 ----------

def _planner_with_conditions(monkeypatch, conditions_by_text, *, radius_by_text=None):
    """② 대역 — 모델 응답(글마다 조건 목록·반경)만 지어 넣고, 줄 나누기는 llm의 진짜 merge_planned가 한다.
    그래서 recommend에 저장된 결과가 constraints.md #419 규칙(조건마다 줄, 같은 키 하나로, 반경은 첫 줄) 그대로인지 본다."""
    from llm.schemas import PlannedCondition, PlannedReason, PlanningOutput

    radius_by_text = radius_by_text or {}

    def planner(raw):
        output = PlanningOutput(reasons=[
            PlannedReason(
                index=i, text=r["text"], circle_radius_m=radius_by_text.get(r["text"]),
                conditions=[PlannedCondition(fact_key=k, wants=w) for k, w in conditions_by_text.get(r["text"], [])],
            )
            for i, r in enumerate(raw)
        ])
        return flows.llm_service.merge_planned(raw, output)

    monkeypatch.setattr(flows.llm_service, "get_evidence_planner", lambda: planner)


def _lines_by_author(db_session, run):
    by_author: dict[str, list[tuple]] = {}
    for l in service.list_evidence(db_session, str(run.id)):
        by_author.setdefault(l.author_id, []).append((l.text, l.chip_id, l.fact_key, l.wants, l.badge, l.circle_radius_m))
    return by_author


def test_create_run_splits_a_reason_into_one_line_per_condition_then_the_chips(db_session, monkeypatch):
    """#419 — "한식 말고 고기 먹고 싶어요"는 같은 글·작성자·배지의 줄 2개(한식 피함, 고기구이 원함). 반경은 첫 줄에만.
    한 반응에서는 글에서 나온 줄들 다음에 칩 줄. 같은 키가 두 번 나오면 하나, 조건 없는 글은 키 없는 줄 하나."""
    _make_members(db_session, user_ids=["user_1", "user_2", "user_3"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="한식 말고 고기 먹고 싶어요",
           reason_chip_ids=["food_oily"])
    _react(db_session, pin, user_id="user_2", type="like", reason_text="고기 좋아요, 고기가 최고")
    _react(db_session, pin, user_id="user_3", type="against", reason_text="그냥 별로예요")
    _planner_with_conditions(monkeypatch, {
        "한식 말고 고기 먹고 싶어요": [("cuisine_korean", False), ("cuisine_bbq", True)],
        "고기 좋아요, 고기가 최고": [("cuisine_bbq", True), ("cuisine_bbq", True)],
    }, radius_by_text={"한식 말고 고기 먹고 싶어요": 800})

    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")

    assert _lines_by_author(db_session, run) == {
        "user_1": [
            ("한식 말고 고기 먹고 싶어요", None, "cuisine_korean", False, "required", 800),
            ("한식 말고 고기 먹고 싶어요", None, "cuisine_bbq", True, "preferred", None),   # #422 — 🚫 안의 음식 종류 "원함"은 선호
            ("느끼해요", "food_oily", "oily_focused", False, "required", None),
        ],
        "user_2": [("고기 좋아요, 고기가 최고", None, "cuisine_bbq", True, "preferred", None)],
        "user_3": [("그냥 별로예요", None, None, None, "required", None)],
    }
    # 거르기는 줄 단위 그대로다 — 나뉜 두 조건이 각각 켜진다(전에는 하나가 조용히 사라졌다).
    # 고기구이 원함은 #422로 선호가 되어 실격 조건이 아니다.
    assert flows._active_soft_requirements(db_session, run) == [("cuisine_korean", False), ("oily_focused", False)]


def test_split_lines_are_turned_off_one_condition_at_a_time(db_session, monkeypatch):
    """#419 — 같은 글에서 나온 줄은 조건 이름으로 구분되고, 「−」는 조건 하나만 끈다."""
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="한식 말고 고기 먹고 싶어요")
    _planner_with_conditions(monkeypatch, {"한식 말고 고기 먹고 싶어요": [("cuisine_korean", False), ("cuisine_bbq", True)]})
    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1")
    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    korean, bbq = flows.list_evidence(db_session, run_id=str(run.id), principal=principal)
    assert korean.text == bbq.text and korean.fact_label != bbq.fact_label

    result = flows.patch_evidence(db_session, run_id=str(run.id), principal=principal, toggles=[(korean.id, False)], adds=[])

    # 순서는 보지 않는다 — 한 트랜잭션에서 넣은 줄은 created_at이 같아 UPDATE 뒤 순서가 바뀔 수 있다(루트 보고).
    assert {e.fact_key: e.is_active for e in result} == {"cuisine_korean": False, "cuisine_bbq": True}
    assert flows._active_soft_requirements(db_session, run) == []   # 남은 고기구이 줄은 #422로 선호라 실격이 아니다


def test_plus_manual_text_with_several_conditions_adds_a_reference_line_per_condition(db_session, monkeypatch):
    """#419 — 「+」 글도 같다. "매운 거랑 회 둘 다 별로예요"는 조건마다 reference 줄 하나다.
    여러 글을 한 번에 더하면 글 순서대로, 글마다 조건 줄들이 붙는다."""
    _planner_with_conditions(monkeypatch, {
        "매운 거랑 회 둘 다 별로예요": [("spicy_focused", False), ("cuisine_raw_fish", False)],
    })
    run = _make_run(db_session, status="collecting_evidence")
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")

    flows.patch_evidence(
        db_session, run_id=str(run.id), principal=principal, toggles=[],
        adds=["매운 거랑 회 둘 다 별로예요", "주차 필요해요"],
    )

    assert _lines_by_author(db_session, run) == {"user_1": [
        ("매운 거랑 회 둘 다 별로예요", None, "spicy_focused", False, "reference", None),
        ("매운 거랑 회 둘 다 별로예요", None, "cuisine_raw_fish", False, "reference", None),
        ("주차 필요해요", None, None, None, "reference", None),
    ]}


def test_preferred_wants_false_subtracts_and_wants_null_has_no_effect(db_session):
    """"한식은 피하고 싶어"(preferred, wants=false)는 한식 참인 후보를 반대 구성원 +1로 깎아 순위가 내려간다.
    wants=NULL 선호(방향을 모름)는 지지도 반대도 아니다(#237)."""
    candidates, _ = _execute_with_lines(
        db_session, [_line("user_1", "preferred", "cuisine_korean", False), _line("user_2", "preferred", "quiet", None)],
        {"korean_quiet": {"cuisine_korean": True, "quiet": True}, "quiet_only": {"quiet": True},
         "korean_only": {"cuisine_korean": True}, "plain": {}},
    )
    ranks = {pid: c.rank for pid, c in candidates.items()}
    assert {ranks["quiet_only"], ranks["plain"]} == {1, 2}  # quiet(wants=NULL)는 0점 — 한식 후보 둘(−1)만 뒤로 밀린다


def test_satisfied_directed_checks_are_shown_as_satisfied(db_session):
    """#237 — "한식 말고"를 만족한 비한식 후보는 ✓, "조용한 곳"(wants=true)은 라벨이 참일 때 ✓. 라벨은 읽을 수 있는 문구."""
    candidates, _ = _execute_with_lines(
        db_session,
        [_line("user_1", "required", "cuisine_korean", False), _line("user_2", "required", "quiet", True)],
        {"ok": {"cuisine_korean": False, "quiet": True}},
    )
    by_key = {c["fact_key"]: c for c in candidates["ok"].checks}
    assert by_key["cuisine_korean"]["passed"] is True and by_key["cuisine_korean"]["label"] == "한식 제외"
    assert by_key["quiet"]["passed"] is True and by_key["quiet"]["label"] == "조용함"


def test_same_key_disqualification_beats_a_supporter(db_session):
    """가드레일 9 — 한 명은 "한식 먹자"(preferred true), 한 명은 "한식 말고"(required false)여도 한식집은 빠진다."""
    candidates, funnel = _execute_with_lines(
        db_session,
        [_line("user_1", "preferred", "cuisine_korean", True), _line("user_2", "required", "cuisine_korean", False)],
        {"korean": {"cuisine_korean": True}, "other": {"cuisine_korean": False}},
    )
    assert set(candidates) == {"other"} and funnel["실격 조건 제거"] == 1


def test_wants_is_stored_and_returned_by_the_evidence_api(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        _line("user_1", "required", "cuisine_korean", False),
        {"author_id": "user_1", "source": "reaction", "text": "옛 데이터", "badge": "reference"},
    ])
    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    by_text = {e.text: e for e in flows.list_evidence(db_session, run_id=str(run.id), principal=principal)}
    assert by_text["사유"].wants is False and by_text["사유"].fact_label == "한식"
    assert by_text["옛 데이터"].wants is None and by_text["옛 데이터"].fact_label is None


def test_candidates_ready_event_payload_validates_as_spec_candidates(db_session):
    """#241 — run.candidates_ready는 스펙의 Candidate 모양(reason·member_fulfillment·permissions 포함)이다."""
    from common.events import EventLog
    from recommend import schemas

    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    places = [PlaceStub(place_id="p1", lat=35.0005, lng=129.0005)]
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts())

    event = db_session.execute(select(EventLog).where(EventLog.type == "run.candidates_ready")).scalars().all()[-1]
    [payload] = event.payload["candidates"]
    candidate = schemas.Candidate(**payload)
    assert candidate.permissions.can_publish is True and candidate.place_name == "이름-p1"
    assert payload["visibility"] == "private" and payload["reason"]


def test_hearted_pin_labels_come_from_place_facts_not_pin_checks(db_session):
    """#247 — 직접 찍은 핀(pins.checks 비어 있음)도 ♥를 받으면 places 라벨이 선호 신호가 된다. 모름 라벨은 0점."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    liked = _make_pin(db_session, lat=35.0008, lng=129.0008)
    assert not liked.checks
    _react(db_session, liked, user_id="user_1", type="like")
    _react(db_session, liked, user_id="user_2", type="like")
    places = [PlaceStub(place_id="near", lat=35.0001, lng=129.0001), PlaceStub(place_id="far_raw", lat=35.005, lng=129.005)]
    facts = _FakePlaceFacts({
        liked.place_id: {"cuisine_raw_fish": True, "quiet": None},
        "near": {"cuisine_raw_fish": False}, "far_raw": {"cuisine_raw_fish": True},
    })
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=facts)
    ranks = {c.place_id: c.rank for c in service.list_candidates(db_session, str(run.id))}
    assert ranks["far_raw"] == 1 and ranks["near"] == 2


def test_restaurant_heart_convenience_labels_do_not_outrank_a_written_preference(db_session):
    """#414 — 명동 시험 재현. ♥ 핀(일식·체인점·기름진 메뉴·주차·넓음) + "초밥 좋아해요"(cuisine_japanese 직접 씀).
    전에는 체인 뷔페가 4점으로 초밥집(2점)보다 위였다. 이제 ♥에서 일식만 남아 초밥집이 1위이고, 뷔페 이유에
    선호 충족이 없다."""
    run = _make_run(db_session, status="collecting_evidence")
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        _line("user_1", "preferred", "cuisine_japanese", True, text="초밥 좋아해요"),
    ])
    liked = _make_pin(db_session, lat=35.0008, lng=129.0008)
    _react(db_session, liked, user_id="user_1", type="like")
    convenience = {"franchise": True, "oily_focused": True, "parking_available": True, "spacious": True}
    places = [PlaceStub(place_id=pid, lat=35.0005, lng=129.0005) for pid in ("buffet", "sushi")]
    facts = _FakePlaceFacts({
        liked.place_id: {"cuisine_japanese": True, **convenience},
        "buffet": {"cuisine_buffet": True, **convenience},
        "sushi": {"cuisine_japanese": True},
    })
    flows.execute_run(db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=facts)

    candidates = {c.place_id: c for c in service.list_candidates(db_session, str(run.id))}
    assert candidates["sushi"].rank == 1 and candidates["buffet"].rank == 2
    assert candidates["sushi"].reason == "선호 충족: 일식 (1/1명)"
    assert "선호 충족" not in candidates["buffet"].reason
    assert "franchise" not in {c["fact_key"] for c in candidates["buffet"].checks}  # ♥에서 빠진 키는 응답 체크에도 없다

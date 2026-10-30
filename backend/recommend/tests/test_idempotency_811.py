"""#811 — 「추천 받기」 멱등 키(Idempotency-Key). 예약은 모델 호출 전에 독립 트랜잭션으로 커밋되므로 실제 커밋과 연결
둘 이상이 필요하다 — db_session(롤백 전용)이 아니라 test_engine에 직접 연결한다."""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import sessionmaker

from common.errors import AppError
from llm.schemas import EvidenceLine as PlannedLine
from recommend import api, core, flows, service
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.models import IdempotencyKey, RecommendRun, Region
from recommend.ports import Circle

USER = "idem_user"
OTHER_USERS = ["idem_other", "idem_from"]


# ---------- 순수 판정 (core) ----------

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _decide(**overrides):
    args = {"stored_hash": "h", "request_hash": "h", "run_id": None, "started_at": NOW, "now": NOW}
    args.update(overrides)
    return core.reservation_decision(**args)


def test_request_hash_is_per_map_category_and_execute_with_default_false():
    base = core.idempotency_request_hash("m1", "카페")
    assert base == core.idempotency_request_hash("m1", "카페", False)
    assert len({
        base, core.idempotency_request_hash("m2", "카페"), core.idempotency_request_hash("m1", "음식점"),
        core.idempotency_request_hash("m1", "카페", True),
    }) == 4


def test_reservation_decision_covers_conflict_reuse_in_progress_and_takeover():
    assert _decide(stored_hash="other") == "conflict"
    assert _decide(stored_hash="other", run_id=uuid.uuid4()) == "conflict"   # 본문이 다르면 run이 있어도 충돌이다
    assert _decide(run_id=uuid.uuid4(), now=NOW + timedelta(days=1)) == "reuse"
    assert _decide(now=NOW + core.IDEMPOTENCY_DEADLINE - timedelta(seconds=1)) == "in_progress"
    assert _decide(now=NOW + core.IDEMPOTENCY_DEADLINE) == "takeover"


# ---------- 실제 PostgreSQL ----------

class _Planner:
    """② 호출을 세는 가짜. 첫 호출은 `release`가 올 때까지 모델을 기다리는 척한다(hold=True)."""

    def __init__(self, *, hold=False, fail_first=False):
        self.calls = 0
        self.hold = hold
        self.fail_first = fail_first
        self.entered = threading.Event()
        self.release = threading.Event()

    def plan_evidence(self, raw):
        self.calls += 1
        first = self.calls == 1
        if first and self.hold:
            self.entered.set()
            self.release.wait(10)
        if first and self.fail_first:
            raise AppError("RECOMMEND_FAILED")
        return [[PlannedLine(**r)] for r in raw]


@pytest.fixture
def env(test_engine, monkeypatch):
    Session = sessionmaker(bind=test_engine)
    map_ids: set[str] = set()
    monkeypatch.setattr(flows, "readiness_for_category", lambda db, **kw: {"ready": True})
    monkeypatch.setattr(
        flows, "_default_circle_and_anchors",
        lambda db, **kw: (Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=1000), [(35.0, 129.0)]),
    )
    monkeypatch.setattr(
        flows.pins_api, "list_reasoned_reactions",
        lambda db, **kw: [{"user_id": USER, "type": "against", "reason_text": "너무 매워요", "chips": []}],
    )

    def create(planner, *, map_id, category="음식점", key="key-00000001", user=USER):
        map_ids.add(map_id)
        session = Session()
        try:
            run = flows.create_run(
                session, map_id=map_id, category=category, requested_by=user, evidence_planner=planner,
                idempotency_key=key,
            )
            session.commit()
            return run.id
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    yield Session, create
    cleanup = Session()
    run_ids = cleanup.execute(select(RecommendRun.id).where(RecommendRun.map_id.in_(map_ids))).scalars().all()
    cleanup.execute(delete(IdempotencyKey).where(IdempotencyKey.requested_by.in_([USER, *OTHER_USERS])))
    cleanup.execute(delete(Region).where(Region.run_id.in_(run_ids)))
    cleanup.execute(delete(EvidenceLineRow).where(EvidenceLineRow.run_id.in_(run_ids)))
    cleanup.execute(delete(RecommendRun).where(RecommendRun.id.in_(run_ids)))
    cleanup.commit()
    cleanup.close()


def _count(Session, model, *conditions):
    with Session() as db:
        return db.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one()


def test_same_key_twice_reuses_the_run_and_calls_the_model_once(env):
    Session, create = env
    planner = _Planner()
    first = create(planner, map_id="idem_map_a")
    second = create(planner, map_id="idem_map_a")
    assert first == second
    assert planner.calls == 1
    assert _count(Session, RecommendRun, RecommendRun.map_id == "idem_map_a") == 1
    with Session() as db:   # 시도 횟수도 한 번만 썼다
        assert service.max_attempt_no_for_requester(db, map_id="idem_map_a", requested_by=USER) == 1


def test_reuse_returns_the_current_state_of_the_run_not_a_copy_of_the_first_response(env):
    Session, create = env
    planner = _Planner()
    run_id = create(planner, map_id="idem_map_b")
    with Session() as db:
        db.execute(update(RecommendRun).where(RecommendRun.id == run_id).values(status="done"))
        db.commit()
    session = Session()
    try:
        reused = flows.create_run(
            session, map_id="idem_map_b", category="음식점", requested_by=USER, evidence_planner=planner,
            idempotency_key="key-00000001",
        )
        assert reused.id == run_id and reused.status == "done"
    finally:
        session.close()


def test_second_request_while_the_first_waits_for_the_model_gets_request_in_progress(env):
    Session, create = env
    planner = _Planner(hold=True)
    results: list[object] = []
    thread = threading.Thread(target=lambda: results.append(create(planner, map_id="idem_map_c")))
    thread.start()
    assert planner.entered.wait(5)   # 첫 요청이 모델을 기다리는 중 — 예약은 이미 커밋됐다
    with pytest.raises(AppError) as in_progress:
        create(planner, map_id="idem_map_c")
    assert in_progress.value.code == "REQUEST_IN_PROGRESS"
    planner.release.set()
    thread.join()
    assert planner.calls == 1   # 둘째는 모델을 부르지 않았다
    assert create(planner, map_id="idem_map_c") == results[0]   # 끝난 뒤에는 같은 run
    assert _count(Session, RecommendRun, RecommendRun.map_id == "idem_map_c") == 1


def test_same_key_with_another_map_or_category_is_a_conflict(env):
    _Session, create = env
    planner = _Planner()
    create(planner, map_id="idem_map_d", category="음식점")
    for other in ({"map_id": "idem_map_e"}, {"map_id": "idem_map_d", "category": "카페"}):
        with pytest.raises(AppError) as conflict:
            create(planner, **other)
        assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    assert planner.calls == 1


def test_same_key_from_another_user_is_independent(env):
    _Session, create = env
    planner = _Planner()
    mine = create(planner, map_id="idem_map_f")
    theirs = create(planner, map_id="idem_map_f", user="idem_other")
    assert mine != theirs and planner.calls == 2


def test_model_failure_releases_the_key_so_the_same_key_can_retry(env):
    Session, create = env
    planner = _Planner(fail_first=True)
    with pytest.raises(AppError) as failed:
        create(planner, map_id="idem_map_g")
    assert failed.value.code == "RECOMMEND_FAILED"
    assert _count(Session, IdempotencyKey, IdempotencyKey.requested_by == USER) == 0
    assert _count(Session, RecommendRun, RecommendRun.map_id == "idem_map_g") == 0   # run도 횟수도 없다
    run_id = create(planner, map_id="idem_map_g")
    assert planner.calls == 2
    assert _count(Session, RecommendRun, RecommendRun.id == run_id) == 1


def test_expired_reservation_is_taken_over_and_the_late_finisher_cannot_save(env):
    Session, create = env
    planner = _Planner(hold=True)
    late: list[str] = []

    def first_request():
        try:
            create(planner, map_id="idem_map_h")
        except AppError as exc:
            late.append(exc.code)

    thread = threading.Thread(target=first_request)
    thread.start()
    assert planner.entered.wait(5)
    with Session() as db:   # 90초가 지난 것으로 만든다
        db.execute(update(IdempotencyKey).where(IdempotencyKey.requested_by == USER).values(
            started_at=datetime.now(timezone.utc) - core.IDEMPOTENCY_DEADLINE - timedelta(seconds=5)))
        db.commit()
    taker_run = create(planner, map_id="idem_map_h")   # 이어받는다(세대 2) — 둘째 호출이라 바로 끝난다
    planner.release.set()
    thread.join()
    assert late == ["REQUEST_IN_PROGRESS"]   # 늦게 끝난 쪽의 run 저장은 거절
    assert _count(Session, RecommendRun, RecommendRun.map_id == "idem_map_h") == 1
    with Session() as db:
        key = db.execute(select(IdempotencyKey).where(IdempotencyKey.requested_by == USER)).scalar_one()
    assert key.run_id == taker_run and key.attempt == 2


def test_no_key_keeps_the_old_behavior(env):
    _Session, create = env
    planner = _Planner()
    first = create(planner, map_id="idem_map_i", key=None)
    second = create(planner, map_id="idem_map_i", key=None)
    assert first != second and planner.calls == 2


# ---------- 정리·합치기 ----------

def test_purge_removes_only_old_rows_that_have_a_run(env):
    Session, create = env
    planner = _Planner()
    create(planner, map_id="idem_map_j", key="key-purge-old")
    create(planner, map_id="idem_map_j", key="key-purge-new")
    old = datetime.now(timezone.utc) - core.IDEMPOTENCY_RETENTION - timedelta(hours=1)
    with Session() as db:
        db.add(IdempotencyKey(requested_by=USER, scope=core.IDEMPOTENCY_SCOPE, key="key-pending-old", request_hash="h",
                              created_at=old))   # 진행 중(run_id NULL)인 옛 예약은 남긴다
        db.execute(update(IdempotencyKey).where(IdempotencyKey.key == "key-purge-old").values(created_at=old))
        db.commit()
    with Session() as db:
        assert api.purge_idempotency_keys(db, now=datetime.now(timezone.utc)) == 1
        db.commit()
    with Session() as db:
        keys = set(db.execute(select(IdempotencyKey.key).where(IdempotencyKey.requested_by == USER)).scalars())
    assert keys == {"key-purge-new", "key-pending-old"}


def test_reassign_user_moves_keys_and_drops_overlapping_ones(env):
    Session, _create = env
    with Session() as db:
        for user, key in (("idem_from", "key-shared-01"), ("idem_from", "key-only-from"), (USER, "key-shared-01")):
            db.add(IdempotencyKey(requested_by=user, scope=core.IDEMPOTENCY_SCOPE, key=key, request_hash="h"))
        db.commit()
    with Session() as db:
        result = service.reassign_user(db, from_user_id="idem_from", to_user_id=USER)
        db.commit()
    assert result["idempotency_keys"] == 1
    with Session() as db:
        rows = db.execute(
            select(IdempotencyKey.requested_by, IdempotencyKey.key).where(IdempotencyKey.key.in_(["key-shared-01", "key-only-from"]))
        ).all()
    assert sorted(tuple(r) for r in rows) == [(USER, "key-only-from"), (USER, "key-shared-01")]

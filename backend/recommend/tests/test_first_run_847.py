"""#847 — 서버 최초 실행(create_run execute=true), 실행 스냅샷(applied_evidence·last_new_count), 새·게시 후보 구분,
조건 0개 고지(no_applied_conditions), 근거 수정의 상한 거절(429 RETRY_LIMIT). 계약은 #845·#851(docs/api-spec.yaml)."""

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from common.errors import AppError
from common.events import EventLog
from recommend import api, constraints, core, flows, service
from recommend.models import Candidate, IdempotencyKey, RecommendRun, Region
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.ports import Circle, PlaceStub
from recommend.tests.test_flows import (
    PLANNER, _FakePlaceFacts, _FakePlaceSearch, _make_members, _make_pin, _make_region, _make_run, _react,
)

USER = "user_1"
PRINCIPAL = Principal(user_id=USER, map_id="map_1", role="member")


def _crowded_line(author="user_1", **overrides):
    return {"author_id": author, "source": "reaction", "text": "너무 붐벼요", "badge": "required",
            "fact_key": "is_crowded_large", **overrides}


def _run_with(db_session, lines, *, category="카페", status="collecting_evidence", **overrides):
    run = _make_run(db_session, status=status, category=category, **overrides)
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=lines)
    return run


def _places(*ids):
    return [PlaceStub(place_id=pid, lat=35.0005 + i * 0.0001, lng=129.0005) for i, pid in enumerate(ids)]


def _facts(*ids):
    return _FakePlaceFacts({pid: {"is_crowded_large": False} for pid in ids})


def _execute(db_session, run, place_ids=("a", "b")):
    return flows.execute_run(
        db_session, run_id=str(run.id), place_search=_FakePlaceSearch(_places(*place_ids)), place_facts=_facts(*place_ids),
    )


def _retry(db_session, run, place_ids=("a", "b")):
    return flows.retry_run(
        db_session, run_id=str(run.id), place_search=_FakePlaceSearch(_places(*place_ids)), place_facts=_facts(*place_ids),
    )


def _result(db_session, run, place_ids=("a", "b")):
    return flows.get_result(db_session, run_id=str(run.id), principal=PRINCIPAL, place_search=_FakePlaceSearch(_places(*place_ids)))


# ---------- 순수 판정 ----------

def test_no_applied_conditions_is_true_when_nothing_enforced_and_false_with_one_enforced_line():
    assert core.no_applied_conditions([]) is True
    assert core.no_applied_conditions([{"enforced": False}, {"enforced": False}]) is True
    assert core.no_applied_conditions([{"enforced": False}, {"enforced": True}]) is False


def test_applied_evidence_entries_use_the_single_enforcement_rule(db_session):
    run = _run_with(db_session, [
        _crowded_line(),                                                       # 실격 조건 — 쓰인다
        {"author_id": "user_2", "source": "reaction", "text": "그냥 싫어", "badge": "required"},   # 키 없음
        {"author_id": "user_2", "source": "reaction", "text": "벚꽃 좋아", "badge": "preferred",
         "fact_key": "cherry_blossom", "wants": True},                        # 시즌 밖이면 안 쓰인다
    ])
    lines = service.list_active_evidence(db_session, run.id)
    entries = core.applied_evidence_entries(lines, "카페", {"cherry_blossom"})
    assert [(e["fact_key"], e["enforced"], e["not_enforced_reason"]) for e in entries] == [
        ("is_crowded_large", True, None), (None, False, "no_key"), ("cherry_blossom", False, "off_season"),
    ]
    assert all(e["is_active"] for e in entries) and entries[0]["author_id"] == "user_1" and entries[0]["text"] == "너무 붐벼요"


# ---------- 스냅샷과 결과 필드 ----------

def test_execute_stores_the_snapshot_and_result_returns_it_with_new_count(db_session):
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run)

    assert run.last_new_count == 2 and run.applied_evidence[0]["enforced"] is True
    result = _result(db_session, run)
    assert result.new_count == 2 and result.no_applied_conditions is False
    assert [(line.fact_key, line.fact_label, line.enforced, line.is_active) for line in result.applied_evidence] == [
        ("is_crowded_large", constraints.FACT_LABELS["is_crowded_large"], True, True),
    ]
    assert result.applied_evidence[0].permissions.can_disable is True   # 본인 줄


def test_snapshot_keeps_the_applied_lines_after_an_edit_until_the_next_run(db_session):
    """고친 근거는 retry가 읽어 반영한다 — 그때까지 결과의 「이 조건으로 찾았어요」(스냅샷)는 실행 당시 그대로다."""
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run)
    line = service.list_active_evidence(db_session, run.id)[0]

    service.set_evidence_active(db_session, line.id, False)   # ×로 뺐다
    db_session.expire_all()
    before_retry = _result(db_session, run)
    assert [applied.id for applied in before_retry.applied_evidence] == [str(line.id)]
    assert before_retry.no_applied_conditions is False

    _retry(db_session, run, place_ids=("a", "b", "c", "d"))   # 지금 후보 a, b는 제외되고 c, d를 새로 찾는다
    after_retry = _result(db_session, run, place_ids=("a", "b", "c", "d"))
    assert after_retry.applied_evidence == [] and after_retry.no_applied_conditions is True


def test_retry_reflects_edits_without_calling_the_model_and_costs_one_attempt(db_session, monkeypatch):
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run)
    attempts = run.attempt_no

    def forbidden(raw):
        raise AssertionError("retry는 모델을 부르지 않는다")

    monkeypatch.setattr(PLANNER, "plan_evidence", forbidden)
    monkeypatch.setattr(flows.llm_api, "plan_evidence", forbidden, raising=False)
    _retry(db_session, run)
    assert run.attempt_no == attempts + 1


def test_a_search_with_zero_new_candidates_but_published_ones_is_a_200_with_new_count_zero(db_session):
    """이번 검색이 0건이어도 이전에 지도에 올린 후보가 남아 있으면 NO_RESULTS가 아니라 200이고 new_count는 0이다."""
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run)
    for candidate in service.list_candidates(db_session, str(run.id)):   # 「지도에 올리기」 — 핀이 생기고 후보가 핀을 가리킨다
        pin = _make_pin(db_session, category="카페", lat=candidate.lat, lng=candidate.lng)
        pin.place_id = candidate.place_id
        candidate.published_pin_id = pin.id
    db_session.flush()

    _retry(db_session, run)   # 게시된 둘은 남고, 그 장소는 지도에 있어 새 후보에서 빠진다 — 새로 찾을 곳이 없다
    result = _result(db_session, run)
    assert result.new_count == 0 and run.last_new_count == 0
    assert sorted(c.visibility for c in result.candidates) == ["published", "published"]


def test_new_count_does_not_change_when_a_candidate_is_published_later(db_session):
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run)
    first = service.list_candidates(db_session, str(run.id))[0]
    db_session.execute(update(Candidate).where(Candidate.id == first.id).values(published_pin_id=uuid.uuid4()))
    db_session.flush()
    db_session.expire_all()
    assert _result(db_session, run).new_count == 2   # 게시해도 마지막 실행이 새로 찾은 수 그대로


def test_no_results_only_when_no_candidates_at_all_and_its_detail_carries_the_snapshot(db_session):
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()])
    _execute(db_session, run, place_ids=())
    with pytest.raises(AppError) as no_results:
        _result(db_session, run, place_ids=())
    assert no_results.value.code == "NO_RESULTS"
    detail = no_results.value.detail
    assert detail["no_applied_conditions"] is False and detail["applied_evidence"][0]["fact_key"] == "is_crowded_large"
    assert "funnel" in detail and "external_search" in detail


def test_run_without_a_snapshot_omits_the_new_fields(db_session):
    """예전 run(스냅샷 없음)은 세 필드를 생략한다 — 필드가 없으면 화면이 지금 표시로 둔다."""
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()], status="done")
    db_session.add(Candidate(run_id=run.id, place_id="a", lat=35.0005, lng=129.0005, rank=1))
    db_session.flush()
    result = _result(db_session, run)
    assert result.applied_evidence is None and result.no_applied_conditions is None and result.new_count is None


# ---------- 최초 실행 (create_run execute=true) ----------

def test_create_run_with_execute_returns_a_done_run_with_candidates_and_the_snapshot(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점", lat=35.0, lng=129.0)
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")
    db_session.commit()

    places = _places("a", "b")
    run = flows.create_run(
        db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=PLANNER,
        execute=True, place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts(),
    )

    assert run.status == "done" and run.attempt_no == 1
    assert len(service.list_candidates(db_session, str(run.id))) == run.last_new_count == 2
    assert [entry["text"] for entry in run.applied_evidence] == ["너무 매워요"]


def test_create_run_without_execute_keeps_the_old_behavior(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")
    db_session.commit()
    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=PLANNER)
    assert run.status == "collecting_evidence" and run.applied_evidence is None and run.last_new_count is None


def test_a_stalled_collecting_run_is_continued_by_execute(db_session):
    """장애로 첫 실행 전에 멈춘 run은 POST /runs/{id}/execute로 이어서 실행한다."""
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()], status="collecting_evidence")
    _execute(db_session, run)
    assert run.status == "done" and run.applied_evidence is not None


@pytest.fixture
def real_env(test_engine, monkeypatch):
    Session = sessionmaker(bind=test_engine)
    monkeypatch.setattr(flows, "readiness_for_category", lambda db, **kw: {"ready": True})
    monkeypatch.setattr(
        flows, "_default_circle_and_anchors",
        lambda db, **kw: (Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=1000), [(35.0, 129.0)]),
    )
    monkeypatch.setattr(
        flows.pins_api, "list_reasoned_reactions",
        lambda db, **kw: [{"user_id": "exec_user", "type": "against", "reason_text": "너무 매워요", "chips": []}],
    )
    yield Session
    cleanup = Session()
    run_ids = cleanup.execute(select(RecommendRun.id).where(RecommendRun.map_id == "exec_map")).scalars().all()
    cleanup.execute(delete(IdempotencyKey).where(IdempotencyKey.requested_by == "exec_user"))
    cleanup.execute(delete(EventLog).where(EventLog.map_id == "exec_map"))   # 실행이 커밋한 run.candidates_ready — 다른 테스트의 개수 단언을 깨지 않게
    cleanup.execute(delete(Candidate).where(Candidate.run_id.in_(run_ids)))
    cleanup.execute(delete(Region).where(Region.run_id.in_(run_ids)))
    cleanup.execute(delete(EvidenceLineRow).where(EvidenceLineRow.run_id.in_(run_ids)))
    cleanup.execute(delete(RecommendRun).where(RecommendRun.id.in_(run_ids)))
    cleanup.commit()
    cleanup.close()


def _count(Session, model, *conditions):
    with Session() as db:
        return db.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one()


def test_a_failure_during_the_first_search_leaves_no_run_no_attempt_and_frees_the_key(real_env, monkeypatch):
    """execute=true는 한 요청·한 트랜잭션이다 — 검색 단계에서 실패해도 run·횟수가 남지 않고 같은 키로 다시 보낼 수 있다."""
    Session = real_env

    def broken(*args, **kwargs):
        raise RuntimeError("검색 장애")

    monkeypatch.setattr(flows, "_run_pipeline", broken)
    session = Session()
    try:
        with pytest.raises(RuntimeError):
            flows.create_run(
                session, map_id="exec_map", category="음식점", requested_by="exec_user", evidence_planner=PLANNER,
                idempotency_key="exec-key-0001", execute=True,
                place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts(),
            )
        session.rollback()   # 요청 끝의 롤백(session_scope)
    finally:
        session.close()
    assert _count(Session, RecommendRun, RecommendRun.map_id == "exec_map") == 0
    assert _count(Session, IdempotencyKey, IdempotencyKey.requested_by == "exec_user") == 0


def test_idempotent_execute_requests_reuse_the_same_done_run(real_env):
    Session = real_env
    planner_calls = []

    class Planner:
        def plan_evidence(self, raw):
            planner_calls.append(raw)
            return PLANNER.plan_evidence(raw)

    def create(execute):
        session = Session()
        try:
            run = flows.create_run(
                session, map_id="exec_map", category="음식점", requested_by="exec_user", evidence_planner=Planner(),
                idempotency_key="exec-key-0002", execute=execute,
                place_search=_FakePlaceSearch(_places("a")), place_facts=_FakePlaceFacts(),
            )
            session.commit()
            return run.id, run.status
        finally:
            session.close()

    first = create(True)
    second = create(True)
    assert first == second and first[1] == "done" and len(planner_calls) == 1
    with pytest.raises(AppError) as conflict:
        create(False)   # execute가 다르면 다른 요청이다 — 같은 키로 보내면 충돌
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"


# ---------- 상한 도달 뒤 근거 수정 거절 ----------

def _patch(db_session, run, *, toggles=(), adds=(), planner=PLANNER):
    return flows.patch_evidence(
        db_session, run_id=str(run.id), principal=PRINCIPAL, toggles=list(toggles), adds=list(adds), evidence_planner=planner,
    )


class _CountingPlanner:
    def __init__(self):
        self.calls = 0

    def plan_evidence(self, raw):
        self.calls += 1
        return PLANNER.plan_evidence(raw)


def test_evidence_edits_are_rejected_with_retry_limit_once_the_requester_used_all_attempts(db_session):
    _make_members(db_session, user_ids=["user_1"])
    run = _run_with(db_session, [_crowded_line()], status="done", attempt_no=core.ATTEMPT_LIMIT)
    line = service.list_active_evidence(db_session, run.id)[0]
    planner = _CountingPlanner()

    for kwargs in ({"toggles": [(str(line.id), False)]}, {"adds": ["조용한 곳"]}):
        with pytest.raises(AppError) as limit:
            _patch(db_session, run, planner=planner, **kwargs)
        assert limit.value.code == "RETRY_LIMIT"
    assert planner.calls == 0   # 모델을 부르기 전에 거절한다
    assert service.list_active_evidence(db_session, run.id)[0].is_active is True   # 아무것도 바뀌지 않았다
    assert len(flows.list_evidence(db_session, run_id=str(run.id), principal=PRINCIPAL)) == 1   # 조회는 된다


def test_the_limit_is_per_requester_and_map_not_per_run_and_the_boundary_is_ten(db_session):
    _make_members(db_session, user_ids=["user_1"])
    _run_with(db_session, [_crowded_line()], status="done", attempt_no=core.ATTEMPT_LIMIT)   # 다른 run에서 다 썼다
    other = _run_with(db_session, [_crowded_line()], status="done", attempt_no=1)
    with pytest.raises(AppError) as limit:
        _patch(db_session, other, adds=["조용한 곳"])
    assert limit.value.code == "RETRY_LIMIT"

    fresh = _run_with(db_session, [_crowded_line("user_9")], status="done", attempt_no=core.ATTEMPT_LIMIT - 1, requested_by="user_9")
    db_session.commit()   # 「+」는 모델 앞에서 읽기 트랜잭션을 롤백한다 — 준비한 데이터는 커밋된 상태여야 한다
    planner = _CountingPlanner()
    _patch(db_session, fresh, adds=["조용한 곳"], planner=planner)   # 9회째까지는 고칠 수 있다(다른 요청자)
    assert planner.calls == 1


# ---------- 탈퇴·나가기·합치기: 스냅샷 안의 사용자 id ----------

def _snapshot_authors(db_session, run):
    db_session.expire_all()
    return [entry["author_id"] for entry in run.applied_evidence]


def test_withdraw_and_leave_drop_the_authors_lines_from_the_snapshot(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2"])
    run = _run_with(db_session, [_crowded_line("user_1"), _crowded_line("user_2", text="저도 붐벼요")])
    _execute(db_session, run)
    other_map = _run_with(db_session, [_crowded_line("user_2")], map_id="map_2")
    _execute(db_session, other_map)

    api.delete_evidence_lines_by_author_in_map(db_session, user_id="user_2", map_id="map_1")   # map_1에서만 나갔다
    assert _snapshot_authors(db_session, run) == ["user_1"]
    assert _snapshot_authors(db_session, other_map) == ["user_2"]

    api.delete_evidence_lines_by_author(db_session, user_id="user_2")   # 탈퇴 — 모든 지도
    assert _snapshot_authors(db_session, other_map) == []
    assert _snapshot_authors(db_session, run) == ["user_1"]


def test_guest_merge_moves_the_snapshot_author_too(db_session):
    _make_members(db_session, user_ids=["user_1", "guest_1"])
    run = _run_with(db_session, [_crowded_line("guest_1"), _crowded_line("user_1", text="나도")])
    _execute(db_session, run)
    result = api.reassign_user(db_session, from_user_id="guest_1", to_user_id="kakao_1")
    assert result["evidence_lines"] == 1
    assert sorted(_snapshot_authors(db_session, run)) == ["kakao_1", "user_1"]

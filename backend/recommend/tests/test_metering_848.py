"""#848 — 모델은 불렸는데 결과가 저장되지 않은 비용을 버려진 호출로 표시하고, GET result가 진행 중인 실행의 커밋을 기다린 뒤 읽는다.

표시는 루트 conftest가 메모리(llm_usage_discards)로 받는다. 경쟁 조건은 진짜 PostgreSQL로 본다."""

import threading
import time
import uuid

import pytest
from sqlalchemy import delete, update
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from common.errors import AppError
from llm import usage
from recommend import core, flows, service
from recommend.models import Candidate, RecommendRun, Region
from recommend.ports import PlaceStub
from recommend.tests.test_flows import (
    PLANNER, _FakePlaceFacts, _FakePlaceSearch, _make_members, _make_pin, _react, _make_run,
)

PRINCIPAL = Principal(user_id="user_1", map_id="map_1", role="member")


class _TracePlanner:
    """dev 통과 스텁처럼 동작하며 호출 안에서 붙어 있는 trace_id를 기록한다."""

    def __init__(self, side_effect=None):
        self.trace_ids = []
        self.side_effect = side_effect

    def plan_evidence(self, raw):
        self.trace_ids.append(usage.current_label().trace_id)
        if self.side_effect:
            self.side_effect()
        return PLANNER.plan_evidence(raw)


def _ready_text_reaction(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점", lat=35.0, lng=129.0)
    _react(db_session, pin, user_id="user_1", type="against", reason_text="너무 매워요")
    db_session.commit()


def test_a_model_call_whose_run_is_not_saved_is_marked_as_discarded_cost(db_session, monkeypatch, llm_usage_discards):
    _ready_text_reaction(db_session)
    planner = _TracePlanner()

    def broken(*args, **kwargs):
        raise RuntimeError("검색 장애")

    monkeypatch.setattr(flows, "_run_pipeline", broken)
    with pytest.raises(RuntimeError):
        flows.create_run(
            db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=planner,
            execute=True, place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts(),
        )
    assert llm_usage_discards == planner.trace_ids and len(planner.trace_ids) == 1


def test_nothing_is_marked_when_the_run_is_saved(db_session, llm_usage_discards):
    _ready_text_reaction(db_session)
    planner = _TracePlanner()
    run = flows.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=planner)
    assert run.status == "collecting_evidence" and len(planner.trace_ids) == 1
    assert llm_usage_discards == []


def test_chips_only_runs_call_no_model_so_there_is_nothing_to_mark(db_session, monkeypatch, llm_usage_discards):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category="음식점")
    _react(db_session, pin, user_id="user_1", type="like")   # 글이 없다 — ②를 부르지 않는다
    db_session.commit()
    monkeypatch.setattr(flows, "_run_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("검색 장애")))
    with pytest.raises(RuntimeError):
        flows.create_run(
            db_session, map_id="map_1", category="음식점", requested_by="user_1", evidence_planner=_TracePlanner(),
            execute=True, place_search=_FakePlaceSearch([]), place_facts=_FakePlaceFacts(),
        )
    assert llm_usage_discards == []


def test_a_plus_rejected_at_save_time_marks_its_model_call_as_discarded(db_session, llm_usage_discards):
    """모델을 기다리는 사이 10회째가 커밋돼 저장 직전 재검사에서 RETRY_LIMIT이면, 이미 나간 모델 호출은 버려진 비용이다."""
    _make_members(db_session, user_ids=["user_1"])
    run = _make_run(db_session, status="done", category="음식점", attempt_no=core.ATTEMPT_LIMIT - 1)
    db_session.commit()

    def tenth_attempt_commits():
        db_session.execute(update(RecommendRun).where(RecommendRun.id == run.id).values(attempt_no=core.ATTEMPT_LIMIT))

    planner = _TracePlanner(side_effect=tenth_attempt_commits)
    with pytest.raises(AppError) as limit:
        flows.patch_evidence(db_session, run_id=str(run.id), principal=PRINCIPAL, toggles=[], adds=["조용한 곳"], evidence_planner=planner)
    assert limit.value.code == "RETRY_LIMIT"
    assert llm_usage_discards == planner.trace_ids and len(planner.trace_ids) == 1


def test_a_plus_that_is_saved_marks_nothing(db_session, llm_usage_discards):
    _make_members(db_session, user_ids=["user_1"])
    run = _make_run(db_session, status="done", category="음식점", attempt_no=1)
    db_session.commit()
    flows.patch_evidence(db_session, run_id=str(run.id), principal=PRINCIPAL, toggles=[], adds=["조용한 곳"], evidence_planner=_TracePlanner())
    assert llm_usage_discards == []


# ---------- GET result는 진행 중인 실행이 끝난 뒤의 값을 읽는다 (진짜 PostgreSQL) ----------

def _places(*ids):
    return [PlaceStub(place_id=pid, lat=35.0005, lng=129.0005) for pid in ids]


def test_get_result_waits_for_a_running_retry_and_never_mixes_old_snapshot_with_new_candidates(test_engine):
    """retry(run 행 FOR UPDATE)가 후보를 교체하고 스냅샷을 덮는 도중에 GET result가 와도, 그 커밋을 기다린 뒤 새 값만 본다.
    잠금이 없으면 GET이 곧바로 이전 실행의 applied_evidence·new_count와 후보를 돌려준다."""
    Session = sessionmaker(bind=test_engine)
    run_id = uuid.uuid4()
    setup = Session()
    setup.add(RecommendRun(
        id=run_id, map_id="map_get_848", category="카페", requested_by="user_1", status="done", attempt_no=1,
        last_new_count=1, applied_evidence=[{
            "id": str(uuid.uuid4()), "author_id": "user_1", "text": "옛 조건", "badge": "required", "fact_key": None,
            "wants": None, "enforced": False, "not_enforced_reason": "no_key", "is_active": True,
        }],
        last_funnel=[],
    ))
    setup.flush()
    setup.add(Region(run_id=run_id, signature="s", label="기본 반경", center_lat=35.0, center_lng=129.0, radius_m=1000,
                     anchor_points=[[35.0, 129.0]], confirmed=True))
    setup.add(Candidate(run_id=run_id, place_id="old_place", lat=35.0005, lng=129.0005, rank=1))
    setup.commit()
    setup.close()

    locked, release = threading.Event(), threading.Event()

    def running_retry():
        session = Session()
        try:
            service.lock_run(session, run_id)   # retry와 같은 잠금
            service.replace_unpublished_candidates(
                session, run_id=run_id, candidates_data=[{"place_id": "new_place", "lat": 35.0005, "lng": 129.0005, "rank": 1}],
            )
            service.set_run_outcome(session, session.get(RecommendRun, run_id), applied_evidence=[], new_count=1)
            locked.set()
            release.wait(10)
            session.commit()
        finally:
            session.close()

    holder = threading.Thread(target=running_retry)
    holder.start()
    results = {}

    def read():
        session = Session()
        try:
            results["result"] = flows.get_result(
                session, run_id=str(run_id), principal=Principal(user_id="user_1", map_id="map_get_848", role="member"), place_search=_FakePlaceSearch(_places("old_place", "new_place")),
            )
            results["finished_at"] = time.monotonic()
        finally:
            session.close()

    try:
        assert locked.wait(5)
        reader = threading.Thread(target=read)
        reader.start()
        time.sleep(0.5)   # GET이 잠금에서 기다리는 중이어야 한다
        assert "result" not in results
        committed_at = time.monotonic()
        release.set()
        holder.join()
        reader.join()
    finally:
        release.set()
        verify = Session()
        verify.execute(delete(Candidate).where(Candidate.run_id == run_id))
        verify.execute(delete(Region).where(Region.run_id == run_id))
        verify.execute(delete(RecommendRun).where(RecommendRun.id == run_id))
        verify.commit()
        verify.close()

    result = results["result"]
    assert results["finished_at"] >= committed_at   # 커밋 뒤에 읽었다
    assert result.applied_evidence == [] and result.new_count == 1   # 새 실행의 스냅샷
    assert [candidate.place_name for candidate in result.candidates] == ["이름-new_place"]   # 새 후보 — 옛 후보와 섞이지 않는다

"""#848 — 「＋」 같은 글 재추가의 멱등(docs/api-spec.yaml PATCH /runs/{runId}/evidence, CHANGELOG 2026-10-30 아홉 번째).

같은 run에서 같은 사람이 이미 쓴 글(앞뒤 공백 제거, 연속 공백 하나로)을 add로 다시 받으면 새 줄 없이 기존 줄을 돌려주고(뺐던
줄이면 다시 켠다) 모델 호출과 글 수 상한 계산에서 뺀다. 다른 사람의 같은 글은 별개의 줄이다."""

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from common.errors import AppError
from recommend import core, flows, service
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.models import RecommendRun
from recommend.tests.test_flows import PLANNER, _make_members, _make_run

ME = Principal(user_id="user_1", map_id="map_1", role="member")
OTHER = Principal(user_id="user_2", map_id="map_1", role="member")


class _Planner:
    def __init__(self):
        self.batches = []

    @property
    def calls(self):
        return len(self.batches)

    def plan_evidence(self, raw):
        self.batches.append([item["text"] for item in raw])
        return PLANNER.plan_evidence(raw)


@pytest.fixture
def run(db_session):
    _make_members(db_session, user_ids=["user_1", "user_2"])
    run = _make_run(db_session, status="done", category="음식점", attempt_no=1)
    db_session.commit()   # 「＋」는 모델 앞에서 읽기 트랜잭션을 롤백한다 — 준비한 데이터는 커밋된 상태여야 한다
    return run


def _add(db_session, run, *texts, principal=ME, planner=None, toggles=()):
    planner = planner or _Planner()
    lines = flows.patch_evidence(
        db_session, run_id=str(run.id), principal=principal, toggles=list(toggles), adds=list(texts), evidence_planner=planner,
    )
    return lines, planner


def _manual(db_session, run, author="user_1"):
    db_session.expire_all()
    return service.list_manual_lines_by_author(db_session, run.id, author)


def test_normalize_manual_text_trims_and_collapses_inner_whitespace():
    assert core.normalize_manual_text("  조용한 \t 곳\n") == "조용한 곳"
    assert core.normalize_manual_text("조용한곳") == "조용한곳"


def test_resending_the_same_text_returns_the_existing_line_without_a_model_call(db_session, run):
    first_lines, first_planner = _add(db_session, run, "조용한 곳")
    db_session.commit()
    again_lines, again_planner = _add(db_session, run, "조용한 곳")

    assert first_planner.calls == 1 and again_planner.calls == 0   # 응답 유실 뒤 재전송 — 모델을 부르지 않는다
    assert [line.id for line in first_lines] == [line.id for line in again_lines]   # 같은 줄 하나
    assert len(_manual(db_session, run)) == 1


def test_whitespace_differences_are_the_same_text(db_session, run):
    _add(db_session, run, "조용한 곳")
    db_session.commit()
    _lines, planner = _add(db_session, run, "  조용한    곳  ")
    assert planner.calls == 0 and len(_manual(db_session, run)) == 1


def test_a_removed_line_is_turned_back_on_without_a_model_call(db_session, run):
    lines, _ = _add(db_session, run, "조용한 곳")
    db_session.commit()
    added_id = next(line.id for line in lines if line.text == "조용한 곳")
    _add(db_session, run, toggles=[(added_id, False)])   # ×로 뺐다
    db_session.commit()
    assert all(not line.is_active for line in _manual(db_session, run))

    again, planner = _add(db_session, run, "조용한 곳")
    assert planner.calls == 0
    assert all(line.is_active for line in _manual(db_session, run)) and len(_manual(db_session, run)) == 1
    assert [line.is_active for line in again if line.text == "조용한 곳"] == [True]


def test_another_persons_same_text_is_a_separate_line_and_calls_the_model(db_session, run):
    _add(db_session, run, "조용한 곳")
    db_session.commit()
    _lines, planner = _add(db_session, run, "조용한 곳", principal=OTHER)
    assert planner.calls == 1
    assert len(_manual(db_session, run, "user_1")) == 1 and len(_manual(db_session, run, "user_2")) == 1


def test_a_mixed_request_sends_only_the_new_text_to_the_model(db_session, run):
    _add(db_session, run, "조용한 곳")
    db_session.commit()
    lines, planner = _add(db_session, run, "조용한 곳", "야경이 좋은 곳", "조용한   곳")
    assert planner.batches == [["야경이 좋은 곳"]]
    mine = {line.text for line in lines if line.author_id == "user_1"}
    assert mine == {"야경이 좋은 곳", "조용한 곳"}   # 응답에는 기존 줄과 새 줄이 모두 있다


def test_repeats_within_one_request_count_once(db_session, run):
    _lines, planner = _add(db_session, run, "조용한 곳", " 조용한  곳", "조용한 곳")
    assert planner.batches == [["조용한 곳"]] and len(_manual(db_session, run)) == 1
    assert service.count_manual_entries(db_session, run.id) == 1   # 상한 계산에도 한 번만 센다


def test_resending_an_existing_text_is_allowed_when_the_run_is_full_but_a_new_text_is_not(db_session, run):
    for i in range(core.MANUAL_EVIDENCE_LIMIT):
        _add(db_session, run, f"글 {i}")
        db_session.commit()
    assert service.count_manual_entries(db_session, run.id) == core.MANUAL_EVIDENCE_LIMIT

    _lines, planner = _add(db_session, run, "글 3")   # 이미 쓴 글 — 상한에 세지 않는다
    assert planner.calls == 0
    with pytest.raises(AppError) as full:
        _add(db_session, run, "새 글")
    assert full.value.code == "EVIDENCE_LIMIT"


def test_stored_text_is_normalized(db_session, run):
    _add(db_session, run, "  조용한    곳 ")
    assert [line.text for line in _manual(db_session, run)] == ["조용한 곳"]


def test_a_resend_at_the_attempt_limit_is_still_rejected_before_anything_changes(db_session):
    """횟수를 다 쓴 요청자는 근거를 고칠 수 없다 — 같은 글 재전송도 요청이라 429다(상한 검사는 멱등 판정보다 앞이다)."""
    _make_members(db_session, user_ids=["user_1"])
    limit_run = _make_run(db_session, status="done", category="음식점", attempt_no=core.ATTEMPT_LIMIT)
    service.add_manual_evidence(db_session, run_id=limit_run.id, author_id="user_1", text="조용한 곳")
    db_session.commit()
    with pytest.raises(AppError) as rejected:
        _add(db_session, limit_run, "조용한 곳")
    assert rejected.value.code == "RETRY_LIMIT"


# ---------- 동시에 같은 글이 두 번 (진짜 PostgreSQL) ----------

def test_two_simultaneous_requests_with_the_same_text_leave_one_line_set(test_engine):
    """연타 — 둘 다 모델 앞 검사(아직 없음)를 통과해 모델을 부르지만, run 잠금 뒤 다시 읽어 둘째는 새 줄을 더하지 않는다."""
    Session = sessionmaker(bind=test_engine)
    run_id = uuid.uuid4()
    setup = Session()
    setup.add(RecommendRun(id=run_id, map_id="map_dup_848", category="음식점", requested_by="dup_user", status="done", attempt_no=1))
    setup.commit()
    setup.close()
    sync = threading.Barrier(2)

    class Planner:
        def plan_evidence(self, raw):
            try:
                sync.wait(timeout=5)   # 둘 다 모델 앞 검사를 통과한 뒤에 쓰기로 넘어간다
            except threading.BrokenBarrierError:
                pass
            return PLANNER.plan_evidence(raw)

    outcomes: list[str] = []

    def request(_i):
        session = Session()
        principal = Principal(user_id="dup_user", map_id="map_dup_848", role="member")
        try:
            flows.patch_evidence(
                session, run_id=str(run_id), principal=principal, toggles=[], adds=["조용한 곳"], evidence_planner=Planner(),
            )
            session.commit()
            outcomes.append("ok")
        except AppError as exc:
            session.rollback()
            outcomes.append(exc.code)
        finally:
            session.close()

    threads = [threading.Thread(target=request, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    verify = Session()
    try:
        assert outcomes == ["ok", "ok"]
        count = verify.execute(select(func.count()).select_from(EvidenceLineRow).where(EvidenceLineRow.run_id == run_id)).scalar_one()
        assert count == 1
    finally:
        verify.execute(delete(EvidenceLineRow).where(EvidenceLineRow.run_id == run_id))
        verify.execute(delete(RecommendRun).where(RecommendRun.id == run_id))
        verify.commit()
        verify.close()

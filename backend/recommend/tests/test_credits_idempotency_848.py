"""크레딧 × 멱등·실패·재실행 점검의 테스트 공백을 메운다(#848 후속, 코드 변경 없음).

추천 차감은 `_create_run` 한 곳 — 모델(②) 뒤, run INSERT와 같은 트랜잭션에서 한다(#949, docs/credits-reviews.md 3.3). 그래서
- ② 단계 실패(30초 상한 포함)는 차감 앞이라 원장·계정 행이 아예 없고,
- 뒤 단계(execute 첫 검색) 실패는 차감이 run과 함께 롤백돼 원장·계정 행이 없고,
- 「＋」(재추가 포함)·×·execute·widen·retry는 크레딧을 건드리지 않는다.
커밋된 원장을 봐야 해서 진짜 커밋이 필요하다(test_engine에 직접 연결)."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from common.events import EventLog
from credits import api as credits_api
from credits.models import CreditAccount, CreditLedger
from llm import api as llm_api
from llm import service as llm_service
from llm.schemas import PlannedReason, PlanningOutput
from llm.service import PLAN_BATCH_SIZE
from recommend import flows
from recommend.models import Candidate, Exclusion, IdempotencyKey, RecommendRun, Region
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.ports import Circle, PlaceStub
from recommend.tests.test_flows import PLANNER, _FakePlaceFacts, _FakePlaceSearch

USER = "cred_user"
MAP = "cred_map"
PRINCIPAL = Principal(user_id=USER, map_id=MAP, role="member")


def _reaction(text="너무 매워요"):
    return {"user_id": USER, "type": "against", "reason_text": text, "chips": []}


@pytest.fixture
def env(test_engine, monkeypatch):
    Session = sessionmaker(bind=test_engine)
    reactions = [_reaction()]
    monkeypatch.setattr(flows, "readiness_for_category", lambda db, **kw: {"ready": True})
    monkeypatch.setattr(
        flows, "_default_circle_and_anchors",
        lambda db, **kw: (Circle(anchor_lat=35.0, anchor_lng=129.0, radius_m=1000), [(35.0, 129.0)]),
    )
    monkeypatch.setattr(flows.pins_api, "list_reasoned_reactions", lambda db, **kw: list(reactions))
    yield Session, reactions
    cleanup = Session()
    run_ids = cleanup.execute(select(RecommendRun.id).where(RecommendRun.map_id == MAP)).scalars().all()
    cleanup.execute(delete(IdempotencyKey).where(IdempotencyKey.requested_by == USER))
    cleanup.execute(delete(EventLog).where(EventLog.map_id == MAP))   # 실행이 커밋한 run.candidates_ready
    cleanup.execute(delete(Exclusion).where(Exclusion.map_id == MAP))   # retry가 넣은 제외 목록(run을 참조한다)
    cleanup.execute(delete(Candidate).where(Candidate.run_id.in_(run_ids)))
    cleanup.execute(delete(Region).where(Region.run_id.in_(run_ids)))
    cleanup.execute(delete(EvidenceLineRow).where(EvidenceLineRow.run_id.in_(run_ids)))
    cleanup.execute(delete(RecommendRun).where(RecommendRun.id.in_(run_ids)))
    cleanup.execute(delete(CreditLedger).where(CreditLedger.user_id == USER))
    cleanup.execute(delete(CreditAccount).where(CreditAccount.user_id == USER))
    cleanup.commit()
    cleanup.close()


def _places(*ids):
    return [PlaceStub(place_id=pid, lat=35.0005 + i * 0.0001, lng=129.0005) for i, pid in enumerate(ids)]


def _search():
    ids = ("a", "b", "c", "d")
    return {"place_search": _FakePlaceSearch(_places(*ids)), "place_facts": _FakePlaceFacts()}


def _spends(Session) -> list[str]:
    with Session() as db:
        return list(db.execute(select(CreditLedger.ref_id).where(
            CreditLedger.user_id == USER, CreditLedger.reason == "spend")).scalars())


def _accounts(Session) -> int:
    with Session() as db:
        return db.execute(select(func.count()).select_from(CreditAccount).where(CreditAccount.user_id == USER)).scalar_one()


def _balance(Session) -> int:
    with Session() as db:
        return credits_api.get_balance(db, user_id=USER)


def _runs(Session) -> int:
    with Session() as db:
        return db.execute(select(func.count()).select_from(RecommendRun).where(RecommendRun.map_id == MAP)).scalar_one()


def _create(Session, planner=PLANNER, **kwargs):
    session = Session()
    try:
        run = flows.create_run(
            session, map_id=MAP, category="음식점", requested_by=USER, evidence_planner=planner, **kwargs,
        )
        session.commit()
        return run.id
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _in_new_session(Session, call):
    session = Session()
    try:
        result = call(session)
        session.commit()
        return result
    finally:
        session.close()


# ---------- 실패는 차감을 남기지 않는다 ----------

class _BatchClient:
    """묶음마다 입력과 맞는 응답을 돌려주는 가짜 모델 클라이언트(llm/tests/test_plan_budget_848.py와 같다)."""

    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls += 1
        payload = json.loads(kwargs["messages"][1]["content"])
        batch = payload["reasons"] if isinstance(payload, dict) and "reasons" in payload else payload
        output = PlanningOutput(reasons=[PlannedReason(index=i, text=r["text"], conditions=[]) for i, r in enumerate(batch)])
        message = SimpleNamespace(parsed=output, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class _RealPlannerGateway:
    """실제 묶음 호출 코드(`_model_planner`)에 가짜 클라이언트를 물린 ② 게이트웨이."""

    def __init__(self, client):
        self.client = client

    def plan_evidence(self, raw):
        return llm_api.plan_evidence(raw, planner=lambda reasons: llm_service._model_planner(self.client, reasons))


def test_thirty_second_budget_failure_leaves_no_run_no_ledger_and_no_account(env, monkeypatch):
    """묶음 호출이 30초 상한에 닿아 실패하면(RECOMMEND_FAILED) 차감 앞이라 run도 원장도 계정 행도 없다."""
    Session, reactions = env
    reactions[:] = [_reaction(f"사유 {i}") for i in range(PLAN_BATCH_SIZE + 1)]   # 묶음 둘
    ticks = iter([0.0, 0.0, 1.0, 29.5])   # deadline 정하기, 묶음1 전·뒤, 묶음2 전(남은 0.5초 — 시작하지 않는다)
    monkeypatch.setattr(llm_service, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    client = _BatchClient()

    with pytest.raises(llm_api.PlanEvidenceFailed):
        _create(Session, planner=_RealPlannerGateway(client))

    assert client.calls == 1   # 첫 묶음만 불렸다 — 모델 비용은 났지만
    assert _runs(Session) == 0 and _spends(Session) == [] and _accounts(Session) == 0   # 사용자는 아무것도 내지 않았다


def test_a_failure_in_the_first_search_rolls_the_charge_back_with_the_run(env, monkeypatch):
    """execute=true는 차감과 첫 검색이 같은 트랜잭션이다 — 검색이 실패하면 차감도 계정 행도 run과 함께 되돌아간다."""
    Session, _reactions = env

    def broken(*args, **kwargs):
        raise RuntimeError("검색 장애")

    monkeypatch.setattr(flows, "_run_pipeline", broken)
    with pytest.raises(RuntimeError):
        _create(Session, execute=True, **_search())
    assert _runs(Session) == 0 and _spends(Session) == [] and _accounts(Session) == 0


# ---------- 성공은 한 번만, 그 뒤 편집·재실행은 차감하지 않는다 ----------

def test_a_successful_create_charges_once_and_edits_and_reruns_charge_nothing(env):
    Session, _reactions = env
    run_id = _create(Session, execute=True, **_search())

    assert _spends(Session) == [f"recommend_run:{run_id}"]   # 대조군: 차감은 정확히 한 번
    balance_after_create = _balance(Session)

    def patch(*, adds=(), toggles=()):
        return _in_new_session(Session, lambda db: flows.patch_evidence(
            db, run_id=str(run_id), principal=PRINCIPAL, toggles=list(toggles), adds=list(adds), evidence_planner=PLANNER,
        ))

    def unchanged(step):
        assert _spends(Session) == [f"recommend_run:{run_id}"], step
        assert _balance(Session) == balance_after_create, step

    lines = patch(adds=["조용한 곳"])        # 「＋」 새 글(모델 호출은 있어도 크레딧은 아니다)
    unchanged("＋ 새 글")
    patch(adds=["  조용한   곳 "])           # 같은 글 재추가(#923) — 새 줄도 차감도 없다
    unchanged("＋ 같은 글 재추가")
    mine = next(line for line in lines if line.text == "조용한 곳")
    patch(toggles=[(mine.id, False)])        # ×
    unchanged("×")
    patch(adds=["조용한 곳"])                # 뺐던 줄 다시 켜기
    unchanged("뺐던 줄 재추가")

    _in_new_session(Session, lambda db: flows.retry_run(db, run_id=str(run_id), **_search()))
    unchanged("retry")
    _in_new_session(Session, lambda db: flows.widen_run(db, run_id=str(run_id), **_search()))
    unchanged("widen")
    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_search()))
    unchanged("execute")


# ---------- 첫 실행이 0곳이면 쓴 크레딧을 돌려준다 (#1015, docs/credits-reviews.md 3.3) ----------
# 환불은 그 run의 첫 실행에서만, 같은 트랜잭션에서 한다. retry·widen은 처음부터 차감이 없고 절대 환불하지 않는다.

def _empty_search():
    return {"place_search": _FakePlaceSearch([]), "place_facts": _FakePlaceFacts()}


def _ledger(Session, reason: str) -> list[tuple[str, int]]:
    with Session() as db:
        rows = db.execute(select(CreditLedger.ref_id, CreditLedger.delta).where(
            CreditLedger.user_id == USER, CreditLedger.reason == reason).order_by(CreditLedger.created_at)).all()
    return [(ref_id, delta) for ref_id, delta in rows]


def _spent_delta(Session) -> int:
    return sum(delta for _ref, delta in _ledger(Session, "spend"))


def test_first_search_with_no_candidates_refunds_in_the_same_transaction(env):
    """① execute:true 첫 검색이 0곳 → 원장에 spend와 refund가 모두 남고 잔액이 원래대로다."""
    Session, _reactions = env
    start = _balance(Session)
    run_id = _create(Session, execute=True, **_empty_search())

    assert _spends(Session) == [f"recommend_run:{run_id}"]
    [(refund_ref, refund_delta)] = _ledger(Session, "refund")
    assert str(run_id) in refund_ref and refund_delta == -_spent_delta(Session)
    assert _balance(Session) == start   # 쓴 만큼 돌려받았다


def test_a_first_search_with_results_keeps_the_charge(env):
    """② 첫 실행이 결과를 냈으면 환불이 없다."""
    Session, _reactions = env
    start = _balance(Session)
    _create(Session, execute=True, **_search())
    assert _ledger(Session, "refund") == []
    assert _balance(Session) == start + _spent_delta(Session) < start


def test_a_later_retry_with_no_results_does_not_refund_the_first_charge(env):
    """③ 첫 실행이 결과를 냈다면 그 뒤 retry가 0건이어도 첫 차감은 그대로다."""
    Session, _reactions = env
    start = _balance(Session)
    run_id = _create(Session, execute=True, **_search())
    after_first = _balance(Session)

    _in_new_session(Session, lambda db: flows.retry_run(db, run_id=str(run_id), **_empty_search()))

    assert _ledger(Session, "refund") == [] and _spends(Session) == [f"recommend_run:{run_id}"]
    assert _balance(Session) == after_first == start + _spent_delta(Session)


def test_widen_with_no_results_never_refunds_and_never_refunds_twice_after_a_zero_first_run(env):
    """④ widen 0건도 환불이 없다. 첫 실행이 0곳이라 한 번 환불된 뒤에는 retry·widen이 0건이어도 환불이 늘지 않는다."""
    Session, _reactions = env
    kept = _create(Session, execute=True, **_search())
    _in_new_session(Session, lambda db: flows.widen_run(db, run_id=str(kept), **_empty_search()))
    assert _ledger(Session, "refund") == []

    start = _balance(Session)
    zero_run = _create(Session, execute=True, **_empty_search(), idempotency_key="zero-run-key-1")
    assert len(_ledger(Session, "refund")) == 1
    balance = _balance(Session)
    assert balance == start   # 두 번째 run의 차감은 환불됐다

    _in_new_session(Session, lambda db: flows.retry_run(db, run_id=str(zero_run), **_empty_search()))
    _in_new_session(Session, lambda db: flows.widen_run(db, run_id=str(zero_run), **_empty_search()))
    assert len(_ledger(Session, "refund")) == 1 and _balance(Session) == balance


def test_the_separate_execute_call_refunds_only_on_the_runs_first_execution(env):
    """⑤ 따로 부르는 POST /runs/{id}/execute — 그 run의 첫 실행이 0곳이면 환불, 이미 실행한 run의 다시 실행은 환불하지 않는다."""
    Session, _reactions = env
    start = _balance(Session)
    run_id = _create(Session)   # execute 없이 — 차감만 하고 collecting_evidence로 둔다
    assert _spends(Session) == [f"recommend_run:{run_id}"] and _ledger(Session, "refund") == []

    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))
    assert len(_ledger(Session, "refund")) == 1 and _balance(Session) == start

    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))   # 이미 실행한 run
    assert len(_ledger(Session, "refund")) == 1

    with_results = _create(Session)   # 첫 실행이 결과를 내는 run은 환불이 없다
    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(with_results), **_search()))
    assert len(_ledger(Session, "refund")) == 1


def test_an_idempotent_resend_does_not_refund_twice(env):
    """⑥ 같은 Idempotency-Key 재전송은 같은 run이고 환불도 한 번이다."""
    Session, _reactions = env
    start = _balance(Session)
    first = _create(Session, execute=True, idempotency_key="refund-key-0001", **_empty_search())
    again = _create(Session, execute=True, idempotency_key="refund-key-0001", **_empty_search())

    assert first == again
    assert len(_ledger(Session, "refund")) == 1 and _spends(Session) == [f"recommend_run:{first}"]
    assert _balance(Session) == start


def test_a_refund_at_the_balance_cap_adds_nothing_but_still_leaves_its_ledger_row(env):
    """⑦ 잔액 상한에서는 환불이 0이어도 refund 원장 줄(ref_id)이 남는다 — 그 run의 환불은 끝났다(멱등)."""
    Session, _reactions = env
    with Session() as db:
        db.add(CreditAccount(user_id=USER, balance=31))   # 상한(30) 위에서 시작 — 차감 뒤 30, 환불로 더 채울 자리가 없다
        db.commit()
    run_id = _create(Session, execute=True, **_empty_search())

    [(refund_ref, refund_delta)] = _ledger(Session, "refund")
    assert str(run_id) in refund_ref and refund_delta == 0
    assert _balance(Session) == 30


# ---------- 지역 확인을 거친 첫 실행 (#1015 검수) ----------
# `regions/confirm`은 검색 없이 상태를 executing으로 바꾼다. 「첫 실행」은 상태가 아니라 실행이 끝난 기록(last_new_count)과 후보 유무로 본다.

def _confirm(Session, run_id):
    _in_new_session(Session, lambda db: flows.confirm_regions(db, run_id=str(run_id), accept_union=False))


def test_first_execute_after_region_confirm_with_no_results_refunds(env):
    """execute:false로 만들고 지역을 확인한 뒤(상태 executing) 첫 execute가 0곳이어도 환불한다."""
    Session, _reactions = env
    start = _balance(Session)
    run_id = _create(Session)   # 차감만 하고 첫 검색은 아직 없다
    _confirm(Session, run_id)
    with Session() as db:
        assert db.get(RecommendRun, run_id).status == "executing"   # 상태 기준이면 첫 실행을 놓치는 자리

    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))

    assert len(_ledger(Session, "refund")) == 1 and _balance(Session) == start


def test_a_failed_first_execute_then_a_zero_result_retry_of_execute_refunds_exactly_once(env, monkeypatch):
    """첫 execute가 실패해(롤백) 상태가 그대로여도, 다시 부른 execute가 0곳이면 환불은 정확히 한 번이다."""
    Session, _reactions = env
    start = _balance(Session)
    run_id = _create(Session)
    _confirm(Session, run_id)

    real_pipeline = flows._run_pipeline
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("검색 장애")
        return real_pipeline(*args, **kwargs)

    monkeypatch.setattr(flows, "_run_pipeline", flaky)
    with pytest.raises(RuntimeError):
        _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))
    assert _ledger(Session, "refund") == [] and _balance(Session) == start + _spent_delta(Session)   # 실패는 환불도 실행 기록도 남기지 않는다

    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))
    assert len(_ledger(Session, "refund")) == 1 and _balance(Session) == start
    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_empty_search()))   # 이미 실행한 run
    assert len(_ledger(Session, "refund")) == 1


def test_a_zero_result_retry_after_a_confirmed_first_execute_with_results_does_not_refund(env):
    """지역 확인을 거친 첫 execute가 결과를 냈다면 그 뒤 재추천(retry) 0건은 환불이 없다."""
    Session, _reactions = env
    run_id = _create(Session)
    _confirm(Session, run_id)
    _in_new_session(Session, lambda db: flows.execute_run(db, run_id=str(run_id), **_search()))
    after_first = _balance(Session)

    _in_new_session(Session, lambda db: flows.retry_run(db, run_id=str(run_id), **_empty_search()))

    assert _ledger(Session, "refund") == [] and _balance(Session) == after_first

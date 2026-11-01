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

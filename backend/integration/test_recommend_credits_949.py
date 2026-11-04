"""「추천 받기」 크레딧 확인·차감(#949, docs/credits-reviews.md 12절 recommend 9~13) — HTTP 끝에서 끝까지.

② 자리에 실제 출구(llm.client.call_planner)를 태우고 네트워크만 가짜다(test_llm_usage.EchoClient). 그래서 "②가 불리지 않는다"를
사용량 기록(llm_calls, #870) 0행으로 본다. 원장은 credits 테이블을 직접 읽는다(credits.api에 원장 조회 함수가 없다).
"""

from functools import partial

import pytest
from sqlalchemy import select

from auth.testing import make_guest
from credits.constants import INITIAL_CREDITS, PRICES
from credits.models import CreditAccount, CreditLedger
from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    _pin, members, own_db, place_ids, plan_with, real_client,
)
from integration.test_llm_usage import EchoClient
from llm import service as llm_service
from recommend.models import RecommendRun

PRICE = PRICES["recommend_run"]   # 가격 숫자는 가격표 한 곳에서 읽는다


@pytest.fixture()
def text_reason_map(members, place_ids, monkeypatch):
    """user_a가 글 사유로 반대한 핀 하나 — 추천을 누르면 ②가 불리는 지도. ②는 실제 출구 + 가짜 네트워크."""
    a, b, map_id = members
    plan_with(monkeypatch, partial(llm_service._model_planner, EchoClient()))
    pin = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": "너무 비싸요"}).status_code == 200
    return a, b, map_id


def _ledger(db_session, user_id):
    return db_session.execute(
        select(CreditLedger.ref_id, CreditLedger.reason, CreditLedger.delta)
        .where(CreditLedger.user_id == user_id)
    ).all()


def _runs(db_session, map_id):
    return db_session.execute(select(RecommendRun.id).where(RecommendRun.map_id == map_id)).scalars().all()


def test_zero_balance_is_402_before_the_model(text_reason_map, db_session, llm_usage_rows):
    """9 — 잔액 0이면 402 CREDIT_INSUFFICIENT이고 ②가 불리지 않는다(llm_calls 0행), run도 차감도 없다."""
    _a, b, map_id = text_reason_map
    db_session.add(CreditAccount(user_id="user_b", balance=0))
    db_session.commit()

    resp = b.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "CREDIT_INSUFFICIENT"
    assert body["detail"] == {"required": PRICE, "balance": 0}
    assert llm_usage_rows == []
    assert _runs(db_session, map_id) == []
    assert _ledger(db_session, "user_b") == []


def test_a_successful_run_spends_one(text_reason_map, db_session, llm_usage_rows):
    """10 — 성공한 run 하나에 원장 recommend_run:<run_id> -1(첫 쓰기라 initial도 함께). 같은 Idempotency-Key 재전송이 차감을
    늘리지 않는지는 실제로 커밋하는 recommend/tests/test_idempotency_811.py가 본다 — 이 픽스처는 연결 하나를 같이 써서 모델 전
    롤백이 독립 트랜잭션의 예약 행까지 되돌린다."""
    _a, b, map_id = text_reason_map

    created = b.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]

    assert sorted(_ledger(db_session, "user_b")) == [
        ("initial:user_b", "initial", INITIAL_CREDITS),
        (f"recommend_run:{run_id}", "spend", -PRICE),
    ]
    assert db_session.get(CreditAccount, "user_b").balance == INITIAL_CREDITS - PRICE
    assert [row["feature"] for row in llm_usage_rows] == ["recommend_run"]


def test_not_ready_spends_nothing(members, db_session, llm_usage_rows):
    """11 — run 생성 중 예외(NOT_READY: 반응이 없다)면 차감도 없다. 계정 행도 만들지 않는다."""
    _a, b, map_id = members
    resp = b.post(f"/maps/{map_id}/runs", json={"category": "음식점", "center": {"lat": 37.5, "lng": 127.0}})   # center는 필수(#1331)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "NOT_READY"
    assert _ledger(db_session, "user_b") == []
    assert db_session.get(CreditAccount, "user_b") is None
    assert llm_usage_rows == []


def test_eleventh_run_retry_and_evidence_edit_pass_without_429(text_reason_map, db_session):
    """12 — 옛 횟수 상한(지도·사람당 10회)이 없다. 11번째 추천, 다시 찾기, 근거 고치기(×·＋)가 모두 통과한다.
    다시 찾기와 근거 고치기는 크레딧을 쓰지 않는다(#432 D5)."""
    a, b, map_id = text_reason_map
    run_ids = []
    for _ in range(11):
        resp = b.post(f"/maps/{map_id}/runs", json={"category": "음식점", "execute": True})
        assert resp.status_code == 202, resp.text
        run_ids.append(resp.json()["id"])
    assert resp.json()["attempt_no"] == 11

    retried = b.post(f"/runs/{run_ids[-1]}/retry")
    assert retried.status_code == 202, retried.text
    assert retried.json()["attempt_no"] == 12

    lines = b.get(f"/runs/{run_ids[-1]}/evidence").json()   # user_a의 글 사유 한 줄 — ×는 작성자만 누른다
    toggled = a.patch(f"/runs/{run_ids[-1]}/evidence", json={"toggle": [{"id": lines[0]["id"], "is_active": False}]})
    assert toggled.status_code == 200, toggled.text
    added = b.patch(f"/runs/{run_ids[-1]}/evidence", json={"add": [{"text": "조용한 곳"}]})
    assert added.status_code == 200, added.text

    spends = [row for row in _ledger(db_session, "user_b") if row.reason == "spend"]
    assert sorted(row.ref_id for row in spends) == sorted(f"recommend_run:{run_id}" for run_id in run_ids)   # 추천 11번만 뺐다
    assert _ledger(db_session, "user_a") == []   # ×를 누른 사람도 쓰지 않는다
    assert db_session.get(CreditAccount, "user_b").balance == INITIAL_CREDITS - 11 * PRICE


def test_guest_is_403_and_the_model_is_not_called(text_reason_map, db_session, llm_usage_rows):
    """13 — 게스트의 POST /maps/{mapId}/runs는 403 GUEST_NOT_ALLOWED(detail.initial_credits)이고 ②가 불리지 않는다."""
    _a, b, map_id = text_reason_map
    make_guest(db_session, "user_b")
    db_session.commit()

    resp = b.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "GUEST_NOT_ALLOWED"
    assert resp.json()["detail"] == {"initial_credits": INITIAL_CREDITS}
    assert llm_usage_rows == []
    assert _runs(db_session, map_id) == []
    assert db_session.get(CreditAccount, "user_b") is None

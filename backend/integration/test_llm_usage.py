"""모델 호출 사용량 기록(llm_calls, #870) — 추천 경로의 라벨, DB에 쓰는 끝단, 탈퇴·합치기·보존.

② 자리에 실제 출구(llm.client.call_planner)를 그대로 태운다. 네트워크만 가짜다(EchoClient — 입력 글을 조건 없이 되돌려 주고
엘리스 게이트웨이 모양의 usage를 붙인다). 진단·요약·코스의 라벨은 agent 테스트가 본다(test_flows_model, test_flows_summary,
agent/course/tests/test_service_db).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    _pin, members, own_db, place_ids, plan_with, real_client,
)
from llm import api as llm_api
from llm import service as llm_service
from llm import usage
from llm.models import LlmCall
from llm.schemas import PlannedReason, PlanningOutput


class EchoClient:
    """chat.completions.parse 대역. 사용자 메시지(JSON 줄 목록)를 읽어 글마다 조건 없는 응답을 만든다."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        lines = json.loads(kwargs["messages"][1]["content"])
        parsed = PlanningOutput(reasons=[PlannedReason(index=l["index"], text=l["text"], conditions=[]) for l in lines])
        message = SimpleNamespace(parsed=parsed, refusal=None, tool_calls=None)
        tokens = SimpleNamespace(prompt_tokens=3700, completion_tokens=90,
                                 prompt_tokens_details=SimpleNamespace(cached_tokens=3600, cache_write_tokens=0))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=tokens)


def test_recommend_run_and_evidence_add_are_recorded_per_call(members, place_ids, monkeypatch, llm_usage_rows):
    a, b, map_id = members
    plan_with(monkeypatch, partial(llm_service._model_planner, EchoClient()))
    pin = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": "너무 비싸요"}).status_code == 200

    run = b.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    assert b.patch(f"/runs/{run_id}/evidence", json={"add": [{"text": "조용한 곳"}, {"text": "주차 되는 곳"}]}).status_code == 200

    recommend, added = llm_usage_rows
    assert (recommend["feature"], recommend["call"], recommend["map_id"], recommend["user_id"]) == (
        "recommend_run", "plan_evidence", map_id, "user_b")
    assert recommend["run_id"] is None   # ②는 run INSERT 전이다(#208)
    assert (added["feature"], added["user_id"], added["run_id"]) == ("evidence_add", "user_b", run_id)
    assert added["trace_id"] != recommend["trace_id"]
    assert (added["input_tokens"], added["cached_input_tokens"], added["output_tokens"]) == (3700, 3600, 90)
    assert added["ok"] is True and added["cost_krw"] > 0
    assert all("비싸요" not in json.dumps(r, default=str, ensure_ascii=False) for r in llm_usage_rows)


def test_run_without_text_reasons_calls_no_model(members, place_ids, monkeypatch, llm_usage_rows):
    a, _, map_id = members
    plan_with(monkeypatch, partial(llm_service._model_planner, EchoClient()))
    pin = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": ["food_spicy"]}).status_code == 200

    assert a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).status_code == 202
    assert llm_usage_rows == []


def _row(user_id="u-guest", *, days_ago=0):
    return LlmCall(
        feature="recommend_run", call="plan_evidence", trace_id=uuid.uuid4(), map_id="m1", user_id=user_id,
        model="gpt-6-luna", input_tokens=100, cached_input_tokens=0, output_tokens=10, cost_krw=0.02,
        outcome="ok", ok=True, elapsed_ms=5, created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def test_default_sink_writes_a_row(db_session, monkeypatch):
    monkeypatch.setattr(usage, "SessionLocal", sessionmaker(bind=db_session.connection(), join_transaction_mode="create_savepoint"))
    monkeypatch.setattr(usage, "sink", usage._write_row)

    with llm_api.usage_context("course", map_id="m9", user_id="u9", run_id="r9"):
        llm_service._model_planner(EchoClient(), [{"source": "reaction", "text": "멀어요", "badge": "required", "fact_key": None}])

    [row] = db_session.execute(select(LlmCall).where(LlmCall.map_id == "m9")).scalars().all()
    assert (row.feature, row.user_id, row.run_id, row.input_tokens, row.cached_input_tokens) == ("course", "u9", "r9", 3700, 3600)
    assert row.cost_krw == usage.cost_krw(usage.TokenCounts(3700, 3600, 0, 90))


def test_withdraw_keeps_rows_but_clears_the_user(db_session, two_users):
    from auth import service as auth_service

    db_session.add_all([_row("user_a"), _row("user_b")])
    db_session.flush()

    auth_service.withdraw_user(db_session, user_id="user_a")

    rows = db_session.execute(select(LlmCall.user_id)).scalars().all()
    assert sorted(rows, key=str) == sorted([None, "user_b"], key=str)


def test_reassign_moves_rows_to_the_kakao_account(db_session):
    db_session.add_all([_row("guest"), _row("guest"), _row("other")])
    db_session.flush()

    assert llm_api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao") == {"llm_calls": 2}
    assert sorted(db_session.execute(select(LlmCall.user_id)).scalars()) == ["kakao", "kakao", "other"]


def test_purge_old_removes_rows_older_than_30_days(db_session):
    db_session.add_all([_row(days_ago=31), _row(days_ago=29)])
    db_session.flush()

    assert llm_api.purge_old(db_session, now=datetime.now(timezone.utc)) == {"llm_calls": 1}
    assert len(db_session.execute(select(LlmCall)).scalars().all()) == 1

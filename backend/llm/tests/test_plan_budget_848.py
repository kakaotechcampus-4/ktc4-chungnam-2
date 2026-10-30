"""#848 — ② 묶음 호출의 누적 시간 상한과 버려진 호출 표시, 묶음 크기 기록.

DB는 쓰지 않는다. 루트 conftest가 llm.usage.sink(행)와 discard_sink(폐기 표시)를 메모리로 바꿔 둔다."""

from types import SimpleNamespace

import pytest

from llm import service, usage
from llm import client as llm_client
from llm.client import LlmCallError, call_planner
from llm.schemas import PlannedReason, PlanningOutput
from llm.service import PLAN_BATCH_SIZE, PlanEvidenceFailed, plan_evidence


def _reasons(count):
    return [{"author_id": "u1", "source": "reaction", "text": f"사유 {i}", "badge": "preferred", "fact_key": None} for i in range(count)]


def _output_for(batch):
    return PlanningOutput(reasons=[PlannedReason(index=i, text=r["text"], conditions=[]) for i, r in enumerate(batch)])


class _Client:
    """묶음마다 입력과 맞는 응답을 돌려주고, 호출을 세며, 선택한 호출 번호(0부터)에서 실패한다."""

    def __init__(self, *, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        index = self.calls
        self.calls += 1
        if index == self.fail_at:
            raise RuntimeError("모델 장애")
        import json
        payload = json.loads(kwargs["messages"][1]["content"])
        batch = payload["reasons"] if isinstance(payload, dict) and "reasons" in payload else payload
        message = SimpleNamespace(parsed=_output_for(batch), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def _real_planner(client):
    return lambda raw: service._model_planner(client, raw)


@pytest.fixture
def labeled():
    with usage.usage_context("recommend_run", map_id="m1", user_id="u1") as label:
        yield label


def test_a_batch_call_records_how_many_reasons_it_carried(labeled, llm_usage_rows):
    client = _Client()
    plan_evidence(_reasons(PLAN_BATCH_SIZE + 3), planner=_real_planner(client))
    assert [(row["call"], row["batch_size"]) for row in llm_usage_rows] == [
        ("plan_evidence", PLAN_BATCH_SIZE), ("plan_evidence", 3),
    ]
    assert len({row["trace_id"] for row in llm_usage_rows}) == 1   # 묶음 수 = 한 trace의 plan_evidence 행 수


def test_a_failing_later_batch_marks_the_earlier_batches_as_discarded_cost(labeled, llm_usage_rows, llm_usage_discards):
    client = _Client(fail_at=1)
    with pytest.raises(PlanEvidenceFailed):
        plan_evidence(_reasons(PLAN_BATCH_SIZE + 3), planner=_real_planner(client))
    assert client.calls == 2
    assert [row["outcome"] for row in llm_usage_rows] == ["ok", "call_failed"]
    assert llm_usage_discards == [labeled.trace_id]   # 앞 묶음은 성공했지만 결과가 쓰이지 않는다 — 버려진 비용


def test_cumulative_time_over_the_budget_stops_the_remaining_batches(labeled, llm_usage_rows, llm_usage_discards, monkeypatch):
    """묶음 호출 누적이 시간 상한을 넘으면 남은 묶음을 부르지 않고 실패한다(PlanEvidenceFailed → RECOMMEND_FAILED)."""
    ticks = iter([0.0, 31.0])   # service가 시계를 읽는 곳: 시작, 둘째 묶음 전(31초 경과). 첫 묶음 전에는 검사하지 않는다
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: next(ticks)))   # client의 시계는 건드리지 않는다
    client = _Client()
    with pytest.raises(PlanEvidenceFailed):
        plan_evidence(_reasons(PLAN_BATCH_SIZE * 3), planner=_real_planner(client))
    assert client.calls == 1   # 첫 묶음만 불렸다
    assert llm_usage_discards == [labeled.trace_id]


def test_within_the_budget_every_batch_is_called_and_nothing_is_discarded(labeled, llm_usage_discards):
    client = _Client()
    groups = plan_evidence(_reasons(PLAN_BATCH_SIZE * 2 + 1), planner=_real_planner(client))
    assert client.calls == 3 and len(groups) == PLAN_BATCH_SIZE * 2 + 1
    assert llm_usage_discards == []


def test_a_failure_in_the_first_batch_marks_only_when_a_label_exists(llm_usage_discards):
    """라벨 밖의 호출(평가 스크립트)은 기록도 표시도 하지 않는다."""
    client = _Client(fail_at=0)
    with pytest.raises(PlanEvidenceFailed):
        plan_evidence(_reasons(2), planner=_real_planner(client))
    assert llm_usage_discards == []


def test_mark_discarded_swallows_sink_errors_and_ignores_empty_input(monkeypatch, caplog):
    def broken(trace_ids):
        raise RuntimeError("DB 장애")

    monkeypatch.setattr(usage, "discard_sink", broken)
    usage.mark_discarded(None)
    usage.mark_discarded([])
    usage.mark_discarded(__import__("uuid").uuid4())   # 예외를 밖으로 던지지 않는다
    assert "RuntimeError" in caplog.text


def test_call_planner_failure_is_recorded_with_its_batch_size(labeled, llm_usage_rows):
    with pytest.raises(LlmCallError):
        call_planner(_Client(fail_at=0), _reasons(4))
    assert llm_usage_rows[0]["batch_size"] == 4 and llm_usage_rows[0]["ok"] is False
    assert llm_client is not None

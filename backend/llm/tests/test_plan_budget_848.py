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
        self.timeouts = []
        self.fail_at = fail_at
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        index = self.calls
        self.calls += 1
        self.timeouts.append(kwargs.get("timeout"))
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


def _clock(monkeypatch, *ticks):
    """service가 시계를 읽을 때마다 ticks를 차례로 돌려준다 — client의 시계는 건드리지 않는다."""
    values = iter(ticks)
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: next(values)))


def test_each_call_gets_a_timeout_of_min_per_call_and_the_remaining_time(labeled, monkeypatch):
    # deadline 정하기(0.0) → 묶음1 전(0.0) → 묶음1 뒤(1.0) → 묶음2 전(20.0, 남은 10초) → 묶음2 뒤(21.0)
    _clock(monkeypatch, 0.0, 0.0, 1.0, 20.0, 21.0)
    client = _Client()
    with service.plan_deadline():
        plan_evidence(_reasons(PLAN_BATCH_SIZE + 1), planner=_real_planner(client))
    assert client.timeouts == [15, 10.0]   # min(15초, 남은 시간)


def test_a_call_starting_just_before_the_limit_runs_with_the_remaining_second(labeled, llm_usage_discards, monkeypatch):
    _clock(monkeypatch, 0.0, 29.0, 29.5)   # deadline, 시작 전(남은 1.0초 = 최소), 끝난 뒤(deadline 안)
    client = _Client()
    with service.plan_deadline():
        groups = plan_evidence(_reasons(2), planner=_real_planner(client))
    assert client.calls == 1 and client.timeouts == [1.0] and len(groups) == 2
    assert llm_usage_discards == []


@pytest.mark.parametrize("started_at", [29.5, 30.0, 40.0])
def test_a_call_is_not_started_when_less_than_the_minimum_time_is_left(labeled, llm_usage_discards, monkeypatch, started_at):
    """29.5초(남은 0.5초), 정확히 30초, 이미 넘긴 시각 — 호출을 시작하지 않고 실패한다(PlanEvidenceFailed → RECOMMEND_FAILED)."""
    _clock(monkeypatch, 0.0, started_at)
    client = _Client()
    with service.plan_deadline(), pytest.raises(PlanEvidenceFailed):
        plan_evidence(_reasons(2), planner=_real_planner(client))
    assert client.calls == 0
    assert llm_usage_discards == [labeled.trace_id]


def test_a_last_batch_that_ends_after_the_deadline_is_a_failure_and_discards_the_earlier_cost(
    labeled, llm_usage_rows, llm_usage_discards, monkeypatch,
):
    """마지막 묶음이 시작 전 검사는 통과했지만 deadline을 넘겨 끝났다 — 응답이 와도 쓰지 않는다. 앞 묶음 비용도 폐기로 표시한다."""
    _clock(monkeypatch, 0.0, 0.0, 10.0, 25.0, 31.0)   # deadline, 묶음1 전·뒤, 묶음2 전(남은 5초), 묶음2 뒤(31초)
    client = _Client()
    with service.plan_deadline(), pytest.raises(PlanEvidenceFailed):
        plan_evidence(_reasons(PLAN_BATCH_SIZE + 1), planner=_real_planner(client))
    assert client.calls == 2 and client.timeouts == [15, 5.0]
    assert llm_usage_discards == [labeled.trace_id]


def test_without_a_deadline_the_planner_sets_its_own_thirty_seconds_at_the_first_call(labeled, monkeypatch):
    _clock(monkeypatch, 100.0, 100.0, 101.0)   # 첫 호출에서 deadline(130) 정하기, 묶음 전, 묶음 뒤
    client = _Client()
    plan_evidence(_reasons(2), planner=_real_planner(client))
    assert client.timeouts == [15]


def test_an_outer_deadline_wins_over_a_longer_inner_one(monkeypatch):
    _clock(monkeypatch, 0.0, 0.0)   # 바깥 deadline 30, 안쪽은 100초를 요청해도 30을 유지
    with service.plan_deadline(30):
        with service.plan_deadline(100):
            assert service._plan_deadline.get() == 30.0


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

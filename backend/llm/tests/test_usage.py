"""모델 호출 사용량 기록(#870) — 출구(client)가 호출마다 한 행을 남기는지, 라벨·토큰·비용·실패 분류가 맞는지.

DB는 쓰지 않는다. 루트 conftest의 llm_usage_rows가 llm.usage.sink를 메모리 목록으로 바꿔 둔다. DB에 쓰는 끝단과 호출 지점의
라벨은 integration/test_llm_usage.py가 본다.
"""

from types import SimpleNamespace

import httpx
import openai
import pytest

from common.settings import settings
from llm import usage
from llm.client import LlmCallError, call_course_direct, call_course_goals, call_planner
from llm.schemas import CourseGoalSet, PlanningOutput, PlannedReason


def _usage(prompt=1000, cached=800, completion=100, cache_write=5):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=cache_write),
    )


class FakeClient:
    """chat.completions.parse만 흉내낸다. 응답에는 엘리스 게이트웨이 모양의 usage가 붙는다(2026-10-30 확인한 필드)."""

    def __init__(self, parsed=None, refusal=None, error=None, usage_=None):
        self._parsed, self._refusal, self._error = parsed, refusal, error
        self._usage = usage_ if usage_ is not None else _usage()
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        if self._error:
            raise self._error
        message = SimpleNamespace(parsed=self._parsed, refusal=self._refusal, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=self._usage)


REASON = {"author_id": "u1", "source": "reaction", "text": "비싸요", "badge": "required", "fact_key": None}
PLANNED = PlanningOutput(reasons=[PlannedReason(index=0, text="비싸요", conditions=[])])


class TestCost:
    def test_cached_part_of_input_uses_cached_price(self):
        counts = usage.TokenCounts(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=1_000_000)
        expected = (600_000 * settings.llm_price_input_krw_per_m + 400_000 * settings.llm_price_cached_input_krw_per_m
                    + 1_000_000 * settings.llm_price_output_krw_per_m) / 1_000_000
        assert usage.cost_krw(counts) == pytest.approx(expected)

    def test_default_prices_match_the_luna_rate_card(self):
        # 입력 ₩141, 캐시 입력 ₩14, 출력 ₩708 (100만 토큰당)
        counts = usage.TokenCounts(input_tokens=2_000_000, cached_input_tokens=1_000_000, output_tokens=1_000_000)
        assert usage.cost_krw(counts) == pytest.approx(141 + 14 + 708)

    def test_cached_more_than_input_is_capped(self):
        assert usage.cost_krw(usage.TokenCounts(input_tokens=10, cached_input_tokens=50)) == pytest.approx(
            10 * settings.llm_price_cached_input_krw_per_m / 1_000_000, abs=1e-4)

    def test_price_comes_from_settings(self, monkeypatch):
        monkeypatch.setattr(usage, "settings", SimpleNamespace(
            llm_price_input_krw_per_m=1_000_000, llm_price_cached_input_krw_per_m=0, llm_price_output_krw_per_m=0,
        ))
        assert usage.cost_krw(usage.TokenCounts(input_tokens=3)) == 3


class TestTokenCounts:
    def test_reads_gateway_fields(self):
        counts = usage.token_counts(SimpleNamespace(usage=_usage(1200, 900, 150, 51)))
        assert counts == usage.TokenCounts(1200, 900, 51, 150)

    def test_missing_details_is_zero(self):
        counts = usage.token_counts(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2)))
        assert (counts.cached_input_tokens, counts.cache_write_tokens) == (0, 0)

    def test_no_response_is_zero(self):
        assert usage.token_counts(None) == usage.TokenCounts()


class TestRecordAtExit:
    def test_success_writes_one_row_with_label(self, llm_usage_rows):
        with usage.usage_context("recommend_run", map_id="m1", user_id="u1") as label:
            call_planner(FakeClient(parsed=PLANNED), [REASON])

        [row] = llm_usage_rows
        assert row["feature"] == "recommend_run" and row["call"] == "plan_evidence"
        assert (row["map_id"], row["user_id"], row["run_id"], row["trace_id"]) == ("m1", "u1", None, label.trace_id)
        assert (row["input_tokens"], row["cached_input_tokens"], row["output_tokens"]) == (1000, 800, 100)
        assert row["cost_krw"] == usage.cost_krw(usage.TokenCounts(1000, 800, 5, 100))
        assert row["outcome"] == "ok" and row["ok"] is True
        assert row["model"] == settings.llm_model

    def test_no_label_writes_nothing(self, llm_usage_rows):
        call_planner(FakeClient(parsed=PLANNED), [REASON])
        assert llm_usage_rows == []

    def test_calls_in_one_context_share_trace(self, llm_usage_rows):
        goals = CourseGoalSet(goals=[], unmatched=[])
        with usage.usage_context("course", map_id="m1", user_id="u1", run_id="r1"):
            call_course_goals(FakeClient(parsed=goals), {"request": "x"})
        with usage.usage_context("course", map_id="m1", user_id="u1", run_id="r2"):
            call_course_goals(FakeClient(parsed=goals), {"request": "y"})
            call_course_goals(FakeClient(parsed=goals), {"request": "z"})

        assert [r["call"] for r in llm_usage_rows] == ["course_goals"] * 3
        assert [r["run_id"] for r in llm_usage_rows] == ["r1", "r2", "r2"]
        assert llm_usage_rows[1]["trace_id"] == llm_usage_rows[2]["trace_id"] != llm_usage_rows[0]["trace_id"]
        assert llm_usage_rows[0]["prompt_version"].startswith("course-goals")

    def test_timeout_is_recorded_as_failure_without_tokens(self, llm_usage_rows):
        error = openai.APITimeoutError(request=httpx.Request("POST", "https://llm.invalid/v1/chat/completions"))
        with usage.usage_context("recommend_run", map_id="m1", user_id="u1"), pytest.raises(LlmCallError):
            call_planner(FakeClient(error=error), [REASON])

        [row] = llm_usage_rows
        assert (row["outcome"], row["ok"], row["input_tokens"], row["cost_krw"]) == ("timeout", False, 0, 0)

    def test_truncated_response_keeps_its_tokens(self, llm_usage_rows):
        # LengthFinishReasonError처럼 예외에 응답이 붙어 오면 그 토큰도 비용이다
        error = RuntimeError("잘림")
        error.completion = SimpleNamespace(usage=_usage(500, 0, 2000, 0), choices=[])
        with usage.usage_context("agent_summary", map_id="m1"), pytest.raises(LlmCallError):
            call_planner(FakeClient(error=error), [REASON])

        [row] = llm_usage_rows
        assert (row["outcome"], row["output_tokens"], row["user_id"]) == ("call_failed", 2000, None)
        assert row["cost_krw"] > 0

    def test_refusal_is_recorded(self, llm_usage_rows):
        with usage.usage_context("course", map_id="m1", user_id="u1"), pytest.raises(LlmCallError):
            call_course_direct(FakeClient(refusal="싫어요"), {"turn": 1}, turn=1)

        [row] = llm_usage_rows
        assert (row["call"], row["outcome"], row["ok"], row["input_tokens"]) == ("course_direct", "refusal", False, 1000)


class TestRecordNeverBreaksTheCall:
    def test_sink_error_is_swallowed(self, monkeypatch, caplog):
        def broken(row):
            raise RuntimeError("db down")
        monkeypatch.setattr(usage, "sink", broken)

        with usage.usage_context("recommend_run", map_id="m1", user_id="u1"):
            out = call_planner(FakeClient(parsed=PLANNED), [REASON])

        assert out == PLANNED
        assert "llm_calls 기록 실패" in caplog.text and "RuntimeError" in caplog.text
        assert "db down" not in caplog.text

    def test_context_resets_after_block(self, llm_usage_rows):
        with usage.usage_context("recommend_run", map_id="m1", user_id="u1"):
            pass
        call_planner(FakeClient(parsed=PLANNED), [REASON])
        assert llm_usage_rows == []

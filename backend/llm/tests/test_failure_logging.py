"""#390 — 모델 호출 실패가 서버 로그에 남는다. 사용자 사유 원문·프롬프트·모델 응답·키는 로그와 detail.reason에 없다."""

import logging
from functools import partial
from types import SimpleNamespace

import httpx
import openai
import pytest
from openai import LengthFinishReasonError
from pydantic import ValidationError

from common.settings import settings
from llm import client as llm_client
from llm import service
from llm.client import LlmCallError, call_planner
from llm.schemas import EvidenceLine, PlanningOutput
from llm.service import PlanEvidenceFailed, plan_evidence

SECRET_REASON = "비밀사유-갑각류알러지-홍길동"
SECRET_KEY = "sk-secret-key-123"
SECRET_BODY = "secret-response-body"


def _reason(text=SECRET_REASON):
    return {"author_id": "u1", "source": "reaction", "text": text, "badge": "required", "fact_key": None}


class FakeClient:
    def __init__(self, parsed=None, refusal=None, error=None, usage=None):
        self._parsed, self._refusal, self._error, self._usage = parsed, refusal, error, usage
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **_kwargs):
        if self._error:
            raise self._error
        message = SimpleNamespace(parsed=self._parsed, refusal=self._refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=self._usage)


def _response(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://x"), headers={"x-request-id": "req-abc"})


def _assert_clean(caplog, *extra_secrets):
    for secret in (SECRET_REASON, SECRET_KEY, SECRET_BODY, settings.elice_ml_api_key or SECRET_KEY, *extra_secrets):
        assert secret not in caplog.text


def test_api_error_is_logged_with_model_batch_status_and_request_id(caplog):
    error = openai.AuthenticationError(f"Incorrect API key: {SECRET_KEY} {SECRET_BODY}", response=_response(401), body=None)

    with caplog.at_level(logging.INFO, logger="pingo.llm"), pytest.raises(LlmCallError):
        call_planner(FakeClient(error=error), [_reason(), _reason()])

    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.name == "pingo.llm"
    for expected in (settings.llm_model, "batch=2", "AuthenticationError", "status_code=401", "request_id=req-abc", "elapsed_ms="):
        assert expected in record.getMessage()
    _assert_clean(caplog)


def test_length_error_logs_completion_tokens_and_finish_reason(caplog):
    completion = SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=2000), choices=[SimpleNamespace(finish_reason="length")],
    )
    error = LengthFinishReasonError(completion=completion)

    with caplog.at_level(logging.INFO, logger="pingo.llm"), pytest.raises(LlmCallError):
        call_planner(FakeClient(error=error), [_reason()])

    assert "completion_tokens=2000" in caplog.text
    assert "finish_reason=length" in caplog.text
    _assert_clean(caplog)


def test_refusal_and_empty_response_are_warned_without_their_content(caplog):
    with caplog.at_level(logging.INFO, logger="pingo.llm"):
        with pytest.raises(LlmCallError):
            call_planner(FakeClient(refusal=SECRET_BODY), [_reason()])
        with pytest.raises(LlmCallError):
            call_planner(FakeClient(parsed=None), [_reason()])

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    _assert_clean(caplog)


def test_success_is_logged_at_info_with_tokens(caplog):
    parsed = PlanningOutput(evidence_lines=[EvidenceLine(source="reaction", text=SECRET_REASON, badge="required")])
    client = FakeClient(parsed=parsed, usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45))

    with caplog.at_level(logging.INFO, logger="pingo.llm"):
        call_planner(client, [_reason()])

    [record] = caplog.records
    assert record.levelno == logging.INFO
    for expected in (settings.llm_model, "batch=1", "prompt_tokens=120", "completion_tokens=45", "elapsed_ms="):
        assert expected in record.getMessage()
    _assert_clean(caplog)


def test_missing_settings_logs_key_names_only(caplog):
    object.__setattr__(settings, "elice_ml_api_base_url", "https://secret-host.example")
    object.__setattr__(settings, "elice_ml_api_key", "")

    with caplog.at_level(logging.INFO, logger="pingo.llm"), pytest.raises(LlmCallError):
        llm_client.make_client()

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "ELICE_ML_API_KEY" in record.getMessage()
    assert "ELICE_ML_API_BASE_URL" not in record.getMessage()  # 설정돼 있는 건 이름도 안 나온다
    assert "secret-host" not in caplog.text


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = (settings.elice_ml_api_base_url, settings.elice_ml_api_key)
    yield
    object.__setattr__(settings, "elice_ml_api_base_url", saved[0])
    object.__setattr__(settings, "elice_ml_api_key", saved[1])


class TestServiceFailureSummary:
    def _validation_error(self):
        try:
            EvidenceLine(source="reaction", text="x", badge=SECRET_REASON)
        except ValidationError as err:
            return err

    def test_validation_error_does_not_leak_the_reason_into_detail_or_logs(self, caplog):
        err = self._validation_error()
        assert SECRET_REASON in str(err)  # 전제: str(ValidationError)에는 입력 원문이 들어 있다

        with caplog.at_level(logging.INFO, logger="pingo.llm"), pytest.raises(PlanEvidenceFailed) as exc:
            plan_evidence([_reason()], planner=partial(service._model_planner, FakeClient(error=err)))

        assert SECRET_REASON not in repr(exc.value.detail) + str(exc.value)
        assert "ValidationError" in exc.value.detail["reason"]
        summary = [r.getMessage() for r in caplog.records if "plan_evidence 실패" in r.getMessage()]
        assert summary and "사유 1개" in summary[0] and "LlmCallError" in summary[0]
        _assert_clean(caplog)

    def test_value_error_from_merge_is_summarized_by_class_name(self, caplog):
        parsed = PlanningOutput(evidence_lines=[])  # 개수 불일치 — merge_planned가 ValueError

        with caplog.at_level(logging.INFO, logger="pingo.llm"), pytest.raises(PlanEvidenceFailed) as exc:
            plan_evidence([_reason()], planner=partial(service._model_planner, FakeClient(parsed=parsed)))

        assert exc.value.detail["reason"].startswith("ValueError")
        assert "응답 개수" not in repr(exc.value.detail)
        _assert_clean(caplog)

"""② Gateway 선택(#219) — LLM_MODE로 dev/real을 고르는 곳은 recommend/deps.py 하나다.
dev는 모델을 부르지 않고 입력을 통과시키고, real은 llm 클라이언트로 부르며 실패하면 PlanEvidenceFailed다."""

from types import SimpleNamespace

import pytest

from llm import client as llm_client
from llm.schemas import PlannedCondition, PlannedReason, PlanningOutput
from llm import service
from llm.service import PlanEvidenceFailed
from recommend import deps

RAW = [{"author_id": "user_1", "source": "reaction", "text": "한식 말고", "badge": "required", "fact_key": None}]


class _FakeClient:
    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls += 1
        parsed = PlanningOutput(reasons=[PlannedReason(
            index=0, text="한식 말고", conditions=[PlannedCondition(fact_key="cuisine_korean", wants=False)],
        )])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))])


def test_dev_gateway_passes_input_through_without_calling_the_model(monkeypatch):
    def forbidden():
        raise AssertionError("dev 모드는 모델 클라이언트를 만들지 않는다")

    monkeypatch.setattr(service, "get_client", forbidden)

    [[line]] = deps.DevEvidencePlanGateway().plan_evidence(RAW)

    assert (line.text, line.fact_key, line.wants) == ("한식 말고", None, None)


def test_real_gateway_structures_the_reason_with_the_model(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(llm_client, "_client", client)

    [[line]] = deps.RealEvidencePlanGateway().plan_evidence(RAW)

    assert client.calls == 1
    assert (line.text, line.fact_key, line.wants, line.badge) == ("한식 말고", "cuisine_korean", False, "required")


def test_real_gateway_fails_instead_of_passing_the_reason_through_when_not_configured(monkeypatch):
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setattr(llm_client, "settings", SimpleNamespace(elice_ml_api_base_url="", elice_ml_api_key="", llm_model="m"))

    with pytest.raises(PlanEvidenceFailed):
        deps.RealEvidencePlanGateway().plan_evidence(RAW)


def test_gateway_is_picked_by_llm_mode():
    assert deps.get_evidence_plan_gateway in (deps._dev_evidence_plan_gateway, deps._real_evidence_plan_gateway)
    assert isinstance(deps._dev_evidence_plan_gateway(), deps.DevEvidencePlanGateway)
    assert isinstance(deps._real_evidence_plan_gateway(), deps.RealEvidencePlanGateway)

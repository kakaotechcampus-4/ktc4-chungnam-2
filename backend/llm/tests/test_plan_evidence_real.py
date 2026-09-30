"""② plan_evidence 실호출 경로 — 네트워크 없이 클라이언트를 대역으로 바꿔 검증한다.

실패 처리 원칙(가드레일 4·8): 호출·검증이 실패하면 "조건 없음"으로 통과시키지 않고
PlanEvidenceFailed(RECOMMEND_FAILED)로 올린다.
"""

from functools import partial
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import ValidationError

from common.settings import settings
from llm import client as llm_client
from llm import service
from llm.client import LlmCallError, call_planner
from llm.schemas import EvidenceLine, PlanningOutput
from llm.service import PlanEvidenceFailed, merge_planned, plan_evidence


def _reason(text="갑각류 알러지 있어요", badge="required", fact_key=None, **extra):
    return {"author_id": "u1", "source": "reaction", "text": text, "badge": badge, "fact_key": fact_key, **extra}


def _planned(text="갑각류 알러지 있어요", badge="required", fact_key=None, **extra):
    return EvidenceLine(source="reaction", text=text, badge=badge, fact_key=fact_key, **extra)


def _output(*lines):
    return PlanningOutput(evidence_lines=list(lines))


class FakeClient:
    """client.chat.completions.parse(...)만 흉내낸다. result는 응답, error는 던질 예외."""

    def __init__(self, parsed=None, refusal=None, error=None, no_choices=False):
        self.calls = []
        self._parsed, self._refusal, self._error, self._no_choices = parsed, refusal, error, no_choices
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        if self._no_choices:
            return SimpleNamespace(choices=[])
        message = SimpleNamespace(parsed=self._parsed, refusal=self._refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _planner(client):
    return partial(service._model_planner, client)


class TestMergePlanned:
    def test_fills_fact_key_from_model_and_keeps_input_fields(self):
        [line] = merge_planned([_reason()], _output(_planned(fact_key="contains_shellfish", author_id="evil")))

        assert line.fact_key == "contains_shellfish"
        assert line.author_id == "u1"  # 모델 값이 아니라 입력 값
        assert line.source == "reaction"

    def test_model_null_fact_key_stays_none(self):
        [line] = merge_planned([_reason(text="그냥 별로예요", badge="preferred")], _output(_planned(text="그냥 별로예요", badge="preferred")))

        assert line.fact_key is None

    def test_input_fact_key_is_not_overwritten_by_model(self):
        [line] = merge_planned([_reason(fact_key="spicy_focused")], _output(_planned(fact_key="quiet")))

        assert line.fact_key == "spicy_focused"

    def test_badge_downgrade_is_ignored(self):
        [line] = merge_planned([_reason(badge="required")], _output(_planned(badge="preferred")))

        assert line.badge == "required"

    def test_badge_upgrade_is_allowed(self):
        [line] = merge_planned([_reason(badge="preferred")], _output(_planned(badge="required")))

        assert line.badge == "required"

    @pytest.mark.parametrize("radius,expected", [(500, 500), (0, None), (-10, None), (None, None)])
    def test_radius_only_when_positive(self, radius, expected):
        [line] = merge_planned([_reason()], _output(_planned(circle_radius_m=radius)))

        assert line.circle_radius_m == expected

    def test_count_mismatch_raises(self):
        with pytest.raises(ValueError, match="개수"):
            merge_planned([_reason(), _reason(text="b")], _output(_planned()))

    def test_text_mismatch_raises(self):
        with pytest.raises(ValueError, match="text"):
            merge_planned([_reason()], _output(_planned(text="다른 문장")))


class TestPlanEvidenceWithModel:
    def test_success_end_to_end(self):
        client = FakeClient(parsed=_output(_planned(fact_key="contains_shellfish")))

        [line] = plan_evidence([_reason()], planner=_planner(client))

        assert line.fact_key == "contains_shellfish"
        assert len(client.calls) == 1

    def test_request_uses_only_model_messages_and_response_format(self):
        # 엘리스 API는 모르는 파라미터를 400으로 거절한다(기획안 13절) — temperature 등을 붙이지 않는다.
        client = FakeClient(parsed=_output(_planned()))

        plan_evidence([_reason()], planner=_planner(client))

        [kwargs] = client.calls
        assert set(kwargs) == {"model", "messages", "response_format"}
        assert kwargs["model"] == settings.llm_model
        assert kwargs["response_format"] is PlanningOutput

    def test_empty_input_does_not_call_model(self):
        client = FakeClient(parsed=_output())

        assert plan_evidence([], planner=_planner(client)) == []
        assert client.calls == []

    @pytest.mark.parametrize(
        "client",
        [
            FakeClient(error=openai.APIConnectionError(request=httpx.Request("POST", "http://x"))),
            FakeClient(error=openai.APITimeoutError(request=httpx.Request("POST", "http://x"))),
            FakeClient(refusal="거절"),
            FakeClient(parsed=None),
            FakeClient(no_choices=True),
            FakeClient(parsed=_output()),  # 개수 불일치
            FakeClient(parsed=_output(_planned(text="변조된 문장"))),  # text 변조
        ],
        ids=["connection", "timeout", "refusal", "parsed-none", "no-choices", "count", "text"],
    )
    def test_failures_raise_instead_of_passing_through(self, client):
        with pytest.raises(PlanEvidenceFailed) as exc:
            plan_evidence([_reason()], planner=_planner(client))

        assert exc.value.code == "RECOMMEND_FAILED"
        assert exc.value.status == 500

    def test_schema_violation_from_sdk_raises(self):
        # SDK가 response_format 검증에 실패하면 ValidationError를 던진다(스키마 밖 fact_key 등).
        try:
            EvidenceLine(source="reaction", text="x", badge="required", fact_key="not_a_key")
        except ValidationError as err:
            client = FakeClient(error=err)

        with pytest.raises(PlanEvidenceFailed):
            plan_evidence([_reason()], planner=_planner(client))

    def test_invalid_input_shape_raises_instead_of_dropping(self):
        client = FakeClient(parsed=_output(_planned()))

        with pytest.raises(PlanEvidenceFailed):
            plan_evidence([{"source": "reaction", "text": "x"}], planner=_planner(client))  # badge 없음

        assert client.calls == []

    def test_error_message_does_not_leak_secrets(self):
        client = FakeClient(error=openai.AuthenticationError(
            "Incorrect API key: sk-secret", response=httpx.Response(401, request=httpx.Request("POST", "http://x")), body=None,
        ))

        with pytest.raises(PlanEvidenceFailed) as exc:
            plan_evidence([_reason()], planner=_planner(client))

        assert "sk-secret" not in str(exc.value)
        assert "sk-secret" not in repr(exc.value.detail)


class TestMakeClient:
    def test_missing_config_fails_before_any_call(self, monkeypatch):
        monkeypatch.setattr(llm_client, "settings", SimpleNamespace(elice_ml_api_base_url="", elice_ml_api_key="k", llm_model="m"))

        with pytest.raises(LlmCallError):
            llm_client.make_client()

    def test_real_planner_with_missing_config_raises_plan_failed(self, monkeypatch):
        monkeypatch.setattr(llm_client, "settings", SimpleNamespace(elice_ml_api_base_url="http://x", elice_ml_api_key="", llm_model="m"))

        monkeypatch.setattr(service, "get_evidence_planner", service._real_evidence_planner)

        with pytest.raises(PlanEvidenceFailed):
            plan_evidence([_reason()])

    def test_call_planner_passes_indexed_payload(self):
        client = FakeClient(parsed=_output(_planned()))

        call_planner(client, [_reason()])

        user_message = client.calls[0]["messages"][1]["content"]
        assert '"index": 0' in user_message
        assert "갑각류 알러지 있어요" in user_message

"""schemas.py의 API 스키마가 docs/api-spec.yaml과 맞는지 — 채운 응답을 스펙 스키마로 검증한다.
그리고 deps.py 고정 응답 스텁이 모델 출력 스키마를 지키는지 본다."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from agent.deps import FixedAgentLlmGateway, get_llm_gateway
from agent.schemas import (
    AgentAction,
    AgentActionParams,
    AgentAdviceLine,
    AgentAnalysis,
    AgentConflictAxis,
    AgentNotFiltered,
    AgentSettings,
    AgentSplitPref,
    AgentState,
    AgentSuggestion,
    AgentSummary,
    AgentUsage,
    AgentSummaryItem,
    AgentVagueFixable,
    DiagnosisOutput,
    RunAdvice,
)

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def _errors(schema_name: str, body) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:pingo-spec#/components/schemas/{schema_name}"}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)]


SUGGESTION = AgentSuggestion(
    id="s1", diagnosis="split", category="음식점", title="의견이 갈린 핀이 있어요",
    analysis=AgentAnalysis(
        conflict_type="same_axis",
        axes=[AgentConflictAxis(label="조용한 곳", like_side="원함 2", against_side=None)],
    ),
    advice=[AgentAdviceLine(text="♥ 2, 🚫 1이에요", is_guess=False)],
    actions=[AgentAction(index=0, type="show_pins", label="핀 보기", params=AgentActionParams(pin_ids=["p1"]))],
    created_at=NOW, expires_at=NOW,
)
SUMMARY = AgentSummary(
    category="음식점",
    must_keep=[AgentSummaryItem(fact_key="spicy_focused", label="매운 곳 제외", member_count=1)],
    common_prefs=[AgentSummaryItem(label="조용한 곳 원함", member_count=3)],
    split_prefs=[AgentSplitPref(fact_key="quiet", label="조용함", want_count=2, avoid_count=1)],
    vague_fixable=AgentVagueFixable(count=1, requests=["거리 조건은 '숙소에서 걸어서 10분'처럼 적어 주세요"]),
    not_filtered=AgentNotFiltered(count=1, notices=["가격은 아직 추천 조건에 없어요."]),
    updated_at=NOW,
)


# FastAPI가 응답을 만들 때처럼 exclude_none 없이 직렬화한다. null이 필수인 칸(category, analysis)은 그대로 null로
# 나가고, params의 채우지 않은 키는 스키마가 스스로 뺀다.
@pytest.mark.parametrize("name, model", [
    ("AgentState", AgentState(
        settings=AgentSettings(enabled=True), active_suggestion=SUGGESTION, has_unseen=True, summaries=[SUMMARY],
    )),
    ("AgentState", AgentState(
        settings=AgentSettings(enabled=False, updated_by="u1", updated_at=NOW),
        active_suggestion=None, has_unseen=False, summaries=[],
    )),
    ("AgentSuggestion", SUGGESTION.model_copy(update={
        "diagnosis": "no_reaction", "category": None, "analysis": None,
        "actions": [AgentAction(index=0, type="show_pins", label="미확인 핀 보기",
                                params=AgentActionParams(pin_ids=["p1"], unseen_only=True))],
    })),
    ("RunAdvice", RunAdvice(
        run_id="r1", kind="radius", advice=[AgentAdviceLine(text="반경을 넓히면 더 나와요", is_guess=False)],
        actions=[AgentAction(index=0, type="widen_radius", label="반경 넓히기", params=AgentActionParams(run_id="r1"))],
    )),
])
def test_filled_response_matches_spec(name, model):
    assert _errors(name, model.model_dump(mode="json")) == []


def test_action_params_drop_unset_keys():
    assert AgentActionParams(category="카페").model_dump(mode="json") == {"category": "카페"}


def test_lengths_follow_spec_max_length():
    with pytest.raises(ValidationError):
        AgentAdviceLine(text="가" * 301, is_guess=False)
    with pytest.raises(ValidationError):
        AgentAction(index=0, type="show_pins", label="가" * 41, params=AgentActionParams())
    with pytest.raises(ValidationError):
        SUGGESTION.model_validate(SUGGESTION.model_dump() | {"title": "가" * 101})


def test_fixed_gateway_is_selected_and_never_suggests():
    gateway = get_llm_gateway()
    assert isinstance(gateway, FixedAgentLlmGateway)

    calls = []

    def runner(call_id, name, args):  # 진단 스텁은 get_reasons를 한 번 부르고 결과는 보지 않는다(#532)
        calls.append((call_id, name, args))
        return {"reasons": [], "total": 0}

    def no_tools(call_id, name, args):
        raise AssertionError(f"도구 호출: {name}")

    diagnosis_reply = gateway.diagnose({"diagnosis": "stall", "signal_id": "s1", "category": "음식점"}, tool_runner=runner)
    diagnosis = diagnosis_reply.result
    assert isinstance(diagnosis, DiagnosisOutput)
    # 고정 응답 스텁은 모델을 부르지 않는다 — 사용량은 없음과 0(#564)
    assert diagnosis_reply.usage == AgentUsage()
    assert not hasattr(gateway, "prioritize")   # 우선순위는 코드 규칙(#582)
    assert (diagnosis.decision, diagnosis.signal_id, diagnosis.advice, diagnosis.actions) == ("silent", "s1", [], [])
    assert calls == [("t1", "get_reasons", {"pin_ids": None, "category": "음식점", "types": None})]

    [[line]] = gateway.structure([{"source": "reaction", "text": "조용해서 좋아요", "badge": "preferred"}])
    assert (line.fact_key, line.badge) == (None, "preferred")   # dev ②는 입력 그대로 — 키를 지어내지 않는다

    assert gateway.summarize({}).decision == "silent"
    advice = gateway.advise_run({}, tool_runner=no_tools)
    assert (advice.decision, advice.actions) == ("silent", [])

"""관찰의 모델 단계(명세 12.4 5, 6단계, #533, #582) — 코드 규칙 우선순위, 진단, 검증, outcome, 모델 사용 집계, 노출.

17절 2(진단 부분), 7(모델 호출 중 상태가 바뀌면 stale), 11(Gateway 호출 중 열린 DB 세션 없음), 2절 13번(저장된 행에 사유
글 없음). Gateway는 이 파일의 대역(FakeGateway)이다 — 고정 응답 스텁(deps.FixedAgentLlmGateway)은 silent만 내서 저장
경로를 지나가지 않는다. 스텁 경로는 test_flows.py의 test_no_agent_row_contains_reason_text가 본다.

사유가 있는 지도는 관찰 끝에 요약 관찰(trigger=summary, #586)도 한 행 남긴다 — 여기서는 지도 관찰 행(trigger=activity)만
본다. 요약은 test_flows_summary.py가 본다.
"""

import json

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from agent import deps, flows, tools
from agent.models import AgentCursor, AgentRun, AgentSuggestion
from agent.schemas import AgentCallFailed, AgentReply, AgentUsage, DiagnosisOutput
from agent.schemas import AgentSuggestion as AgentSuggestionSchema
from agent.tests.world import World, fake_places, real_now
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from llm import api as llm_api
from places import api as places_api
from recommend import api as recommend_api

LIKE_TEXT = "분위기가 아늑해서 오래 있기 좋아요"
AGAINST_TEXT = "주차할 곳이 전혀 없어서 힘들어요"


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


class FakeGateway:
    """Gateway 대역. diagnose는 llm.agent_diagnose처럼 call_id를 매겨 tool_runner를 부를 수 있게 call_tool을 넘긴다.
    Gateway에 없는 이름(예: 지운 prioritize, #582)을 찾으면 그 이름을 calls에 남기고 실패한다."""

    def __init__(self, diagnose=None, on_call=None, diagnosis_usage=None):
        self._diagnose = diagnose
        self.on_call = on_call or (lambda what: None)
        self._diagnosis_usage = diagnosis_usage or AgentUsage()
        self.calls: list[str] = []
        self.inputs: list[dict] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self.calls.append(name)
        raise AttributeError(f"Gateway에 없는 호출: {name}")

    def diagnose(self, diagnosis_input, *, tool_runner):
        self.calls.append("diagnose")
        self.inputs.append(diagnosis_input)
        self.on_call("diagnose")
        counter = iter(range(1, 100))

        def call_tool(name, args):
            call_id = f"t{next(counter)}"
            try:
                result = tool_runner(call_id, name, args)
            except Exception as exc:   # llm.agent_diagnose처럼 감싸 그때까지의 사용량을 붙여 올린다(#677)
                error = llm_api.ToolRunnerError(f"tool_runner 실패: {name} {type(exc).__name__}")
                error.usage = self._diagnosis_usage
                raise error from exc
            return {"call_id": call_id, "result": result}

        out = self._diagnose(diagnosis_input, call_tool) if self._diagnose else None
        self.on_call("diagnose_done")
        return AgentReply(out, self._diagnosis_usage)

    def structure(self, raw):
        return llm_api.plan_evidence(raw, planner=llm_api.passthrough_planner)


def observe(world, map_id, gateway):
    return flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway)


def suggestion_events(world, map_id):
    """제안 이벤트만 — 사유가 있는 지도는 관찰 끝에 요약도 갱신해 agent.summary_updated가 함께 나간다(#586)."""
    return [e for e in world.agent_events(map_id) if e[0] != "agent.summary_updated"]


def _split_map(world):
    """의견 갈림(전원 응답) + 반대 후 정체가 함께 있는 지도. 음식점 핀 하나에 u1 ♥(글), u2 ♥, u3 🚫(글)."""
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    like = world.react(pin_id, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(pin_id, "u2", "like", hours_ago=25)
    against = world.react(pin_id, "u3", "against", hours_ago=20, text=AGAINST_TEXT)
    world.event(map_id)
    return map_id, pin_id, like, against


def _stall_map(world):
    """반대 후 정체만 있는 지도 — 음식점 핀 하나에 u2 🚫(글) 20시간 전."""
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    against = world.react(pin_id, "u2", "against", hours_ago=20, text=AGAINST_TEXT)
    world.event(map_id)
    return map_id, pin_id, against


def good_split(inp, call_tool):
    """도구로 사유를 읽고 검증을 통과하는 진단을 낸다."""
    reasons = call_tool("get_reasons", {"pin_ids": [inp["pin_id"]], "category": None, "types": None})
    against = next(r for r in reasons["result"]["reasons"] if r["type"] == "against")
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "split", "signal_id": inp["signal_id"],
        "claims": [
            {"id": "c1", "kind": "count", "subject": "pin", "subject_id": inp["pin_id"], "metric": "like", "value": 2},
            {"id": "c2", "kind": "count", "subject": "pin", "subject_id": inp["pin_id"], "metric": "against",
             "value": 1},
            {"id": "c3", "kind": "quote", "reaction_id": against["reaction_id"], "text": against["text"][:8]},
            {"id": "c4", "kind": "tool_result", "call_id": reasons["call_id"], "path": "total", "value": 2},
        ],
        "advice": [
            {"text": "♥ {c1.value}명, 🚫 {c2.value}명으로 갈렸어요", "basis": ["c1", "c2"], "is_guess": False},
            {"text": "🚫 쪽은 {c3}라고 했어요", "basis": ["c3"], "is_guess": False},
        ],
        "actions": [{"type": "open_recommend", "category": "음식점", "pin_ids": None, "basis": ["c1"]}],
    })


def good_stall(inp, call_tool):
    ready = call_tool("get_readiness", {"category": inp["category"]})
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "stall", "signal_id": inp["signal_id"],
        "claims": [{"id": "c1", "kind": "tool_result", "call_id": ready["call_id"], "path": "ready", "value": True}],
        "advice": [{"text": "반대 의견을 반영해 다시 추천받아 볼 수 있어요", "basis": ["c1"], "is_guess": True}],
        "actions": [{"type": "open_recommend", "category": None, "pin_ids": None, "basis": ["c1"]}],
    })


def _dump_agent_rows(factory) -> str:
    with factory() as db:
        return json.dumps([
            db.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all()
            for table in ("agent_runs", "agent_suggestions")
        ], ensure_ascii=False)


# ---------------------------------------------------------------- 진단 → 제안 (17절 2번 진단 부분)

def test_split_diagnosis_is_verified_and_saved(world, factory):
    map_id, pin_id, like, against = _split_map(world)
    gateway = FakeGateway(diagnose=good_split)

    assert observe(world, map_id, gateway) == "suggested"

    assert gateway.calls == ["diagnose"]   # 우선순위 모델은 없다(#582)
    [inp] = gateway.inputs
    assert inp["pin_id"] == pin_id and inp["comparison"]["conflict_type"] == "unclear"   # dev ②는 키를 안 붙인다
    sug = world.one(AgentSuggestion, map_id=map_id)
    assert (sug.diagnosis, sug.shadow, sug.title, sug.pin_id is not None) == ("split", False, "의견이 갈린 핀이 있어요", True)
    quote = next(c for c in sug.claims if c["kind"] == "quote")
    # 인용은 id와 검증한 범위, 그 범위의 다이제스트만(원문 없음, #717)
    assert (quote["reaction_id"], quote["start"], quote["end"]) == (against, 0, 8)
    assert set(quote) == {"id", "kind", "reaction_id", "start", "end", "digest"}
    assert sug.analysis == inp["comparison"]
    assert sug.actions == [{"index": 0, "type": "open_recommend", "label": "음식점 추천 받기",
                            "params": {"category": "음식점"}}]
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert (run.outcome, run.used_model, run.priority["source"]) == ("suggested", True, "rules")
    # 정체(영향 1명)가 먼저 탐지됐지만 같은 weight에서 영향 인원이 많은 갈림(3명)이 1순위다
    assert [s["diagnosis"] for s in run.signals] == ["stall", "split"]
    assert (run.priority["final_order"], run.priority["rule_hits"]) == (["s2", "s1"], ["affected_members"])
    assert run.verification["established"] is True and run.verification["claims"]["removed"] == []
    assert [c["name"] for c in run.tool_calls] == ["get_reasons"]
    [(type_, payload)] = suggestion_events(world, map_id)   # 모델 유형도 노출(#582)
    assert (type_, payload["id"], payload["diagnosis"]) == ("agent.suggested", str(sug.id), "split")
    # 이벤트도 응답과 같은 조각 모양이고, 인용은 검증한 앞 8글자만 나간다 — 사유 글 전체가 아니다(#717)
    assert payload["advice"][1]["segments"] == [
        {"kind": "text", "text": "🚫 쪽은 "}, {"kind": "quote", "text": AGAINST_TEXT[:8], "reaction_id": against},
        {"kind": "text", "text": "라고 했어요"},
    ]
    assert AGAINST_TEXT not in json.dumps(payload, ensure_ascii=False)
    dumped = _dump_agent_rows(factory)
    assert LIKE_TEXT not in dumped and AGAINST_TEXT not in dumped and AGAINST_TEXT[:8] not in dumped


def test_stall_diagnosis_uses_readiness_tool(world):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, FakeGateway(diagnose=good_stall)) == "suggested"

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert (sug.diagnosis, sug.category, sug.shadow) == ("stall", "음식점", False)
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.priority["source"] == "single" and run.used_model is True   # 진단만 불러도 1회
    assert run.tool_calls[0]["name"] == "get_readiness" and run.tool_calls[0]["result"]["ready"] is True


# ---------------------------------------------------------------- outcome 매핑

@pytest.mark.parametrize("failed, outcome", [
    (AgentCallFailed(reason="call_failed", detail="LlmCallError(APIError)"), "model_failed"),
    (AgentCallFailed(reason="timeout", detail="LlmCallError(APITimeoutError)"), "model_failed"),
    (AgentCallFailed(reason="invalid_schema", detail="ValidationError(ValidationError)"), "invalid_schema"),
])
def test_failed_call_is_silent_with_reason(world, failed, outcome):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, FakeGateway(diagnose=lambda inp, call: failed)) == outcome

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.outcome_detail == {"signal_id": "s1", "diagnosis": "stall", "reason": failed.reason,
                                  "detail": failed.detail}
    assert run.used_model is True and run.verification is None
    assert world.rows(AgentSuggestion, map_id=map_id) == []


@pytest.mark.parametrize("decision", ["silent", "unknown"])
def test_model_silence_is_recorded(world, decision):
    map_id, _, _ = _stall_map(world)

    def silent(inp, call):
        return DiagnosisOutput(decision=decision, diagnosis="stall", signal_id=inp["signal_id"], claims=[],
                               advice=[], actions=[])

    assert observe(world, map_id, FakeGateway(diagnose=silent)) == decision
    assert world.one(AgentRun, map_id=map_id, trigger="activity").verification == {"decision": decision}


def test_failed_verification_is_invalid_claims(world):
    map_id, _, _ = _stall_map(world)

    def made_up(inp, call):
        out = good_stall(inp, call)
        claim = out.claims[0].model_copy(update={"value": False})   # 도구 결과와 다른 값
        return out.model_copy(update={"claims": [claim]})

    assert observe(world, map_id, FakeGateway(diagnose=made_up)) == "invalid_claims"

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.verification["claims"]["removed"] == [{"id": "c1", "reason": "tool_mismatch"}]
    assert run.verification["failed_step"] == 7
    assert run.outcome_detail == {"signal_id": "s1", "diagnosis": "stall", "decision": "suggest"}


def test_fixed_gateway_reads_reasons_and_stays_silent(world):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, deps.FixedAgentLlmGateway()) == "silent"

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert [c["name"] for c in run.tool_calls] == ["get_reasons"] and run.used_model is True


# ---------------------------------------------------------------- 7. 모델 호출 중 상태가 바뀌면 stale

def test_pin_confirmed_during_diagnosis_makes_it_stale(world):
    map_id, pin_id, _, _ = _split_map(world)

    def confirm_during(what):
        if what == "diagnose":
            world.confirm(map_id, pin_id, hours_ago=0)   # 다른 연결에서 커밋

    gateway = FakeGateway(diagnose=good_split, on_call=confirm_during)

    assert observe(world, map_id, gateway) == "stale"
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    assert world.one(AgentRun, map_id=map_id, trigger="activity").used_model is True


def test_reaction_changed_during_diagnosis_makes_it_stale(world):
    map_id, _, against = _stall_map(world)

    def edit_during(what):
        if what == "diagnose":
            world.touch_reaction(against, hours_ago=0, text="생각해 보니 괜찮아요")

    assert observe(world, map_id, FakeGateway(diagnose=good_stall, on_call=edit_during)) == "stale"
    assert world.rows(AgentSuggestion, map_id=map_id) == []


# ---------------------------------------------------------------- 11. Gateway 호출 중 열린 DB 세션 없음

def test_no_db_connection_is_held_while_model_is_called(world, test_engine):
    map_id, _, _, _ = _split_map(world)
    held: dict[str, int] = {}

    def check(what):
        held[what] = test_engine.pool.checkedout()

    gateway = FakeGateway(diagnose=good_split, on_call=check)

    assert observe(world, map_id, gateway) == "suggested"
    assert held == {"diagnose": 0, "diagnose_done": 0}   # 도구가 연 세션도 닫혔다


# ---------------------------------------------------------------- 우선순위는 모델을 부르지 않는다 (7절, #582)

def test_gateway_has_no_priority_call():
    for gateway in (deps.AgentLlmGateway, deps.FixedAgentLlmGateway, deps.RealAgentLlmGateway):
        assert not hasattr(gateway, "prioritize")


def test_observation_with_several_model_signals_never_asks_for_priority(world):
    """모델 유형 둘(정체, 갈림)이 함께 통과해도 순위는 코드 규칙이다. Gateway에는 진단만 간다."""
    map_id, _, _, _ = _split_map(world)
    gateway = FakeGateway(diagnose=silent)

    assert observe(world, map_id, gateway) == "silent"

    assert gateway.calls == ["diagnose"]
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert set(run.priority) == {"source", "final_order", "fingerprints", "rule_hits"}
    assert run.priority["source"] == "rules"


# ---------------------------------------------------------------- 모델 사용 1회는 진단만 센다 (3절, 12.3)

def _gap_and_stall_map(world, *, days_to_start):
    """확정 2곳(음식점)으로 카테고리 공백 둘(카페, 관광지)과 카페 반대 후 정체가 함께 있는 지도."""
    map_id = world.gap_map(start=world.today + timedelta(days=days_to_start))
    cafe = world.pin(map_id, category="카페", hours_ago=100)
    world.react(cafe, "u2", "against", hours_ago=20, text=AGAINST_TEXT)
    world.event(map_id)
    return map_id


def _model_runs_today(world, map_id):
    with world.factory() as db:
        return flows.service.load_history(db, map_id, world.now).model_runs_today


def test_model_use_counts_only_diagnosis(world):
    """출발 임박이면 카테고리 공백이 1순위라 진단을 부르지 않는다 — 모델 유형 신호가 있어도 모델 사용 0회. 출발이
    멀면 정체가 1순위라 진단 1회. 우선순위는 어느 쪽이든 세지 않는다."""
    near = _gap_and_stall_map(world, days_to_start=2)
    far = _gap_and_stall_map(world, days_to_start=30)
    gateway = FakeGateway(diagnose=silent)

    assert observe(world, near, gateway) == "suggested"
    assert gateway.calls == []
    run = world.one(AgentRun, map_id=near, trigger="activity")
    assert (run.used_model, run.priority["rule_hits"]) == (False, ["urgent_dday"])
    assert world.one(AgentSuggestion, map_id=near).diagnosis == "category_gap"
    assert _model_runs_today(world, near) == 0

    assert observe(world, far, gateway) == "silent"
    assert gateway.calls == ["diagnose"]
    run = world.one(AgentRun, map_id=far, trigger="activity")
    assert (run.used_model, run.priority["source"], run.priority["rule_hits"]) == (True, "rules", [])
    assert _model_runs_today(world, far) == 1


def test_each_diagnosis_counts_once(world):
    map_id, _, _, _ = _split_map(world)
    gateway = FakeGateway(diagnose=silent)

    observe(world, map_id, gateway)
    observe(world, map_id, gateway)

    assert gateway.calls == ["diagnose", "diagnose"]
    assert [r.used_model for r in world.rows(AgentRun, map_id=map_id, trigger="activity")] == [True, True]
    assert _model_runs_today(world, map_id) == 2   # 관찰마다 1회


def test_model_cap_blocks_model_types_and_code_types_go_on(world, monkeypatch):
    map_id = _gap_and_stall_map(world, days_to_start=30)
    monkeypatch.setattr(flows.core, "PER_MEMBER_DAILY_MODEL_USES", 0)   # 상한 0 — 이미 도달
    gateway = FakeGateway(diagnose=silent)

    assert observe(world, map_id, gateway) == "suggested"

    assert gateway.calls == []
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert [b["reason"] for b in run.blocked] == ["model_cap"]
    assert (run.used_model, run.priority["source"]) == (False, "rules")
    assert world.one(AgentSuggestion, map_id=map_id).diagnosis == "category_gap"


def silent(inp, call_tool):
    return DiagnosisOutput(decision="silent", diagnosis=inp["diagnosis"], signal_id=inp["signal_id"],
                           claims=[], advice=[], actions=[])


def test_code_only_signals_do_not_use_model(world):
    map_id = world.gap_map()   # 코드 유형 신호 둘
    world.event(map_id)
    gateway = FakeGateway()

    assert observe(world, map_id, gateway) == "suggested"

    assert gateway.calls == []
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert (run.priority["source"], run.used_model) == ("rules", False)
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (None, None, 0, 0)


# ---------------------------------------------------------------- 사용량과 축 이름 (#564)

LUNA = "gpt-6-luna"


def test_diagnosis_usage_is_recorded_in_the_run(world):
    map_id, _, _, _ = _split_map(world)
    gateway = FakeGateway(
        diagnose=good_split,
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v2", tokens_in=900, tokens_out=200),
    )

    assert observe(world, map_id, gateway) == "suggested"

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (LUNA, "diagnose-v2", 900, 200)


def test_failed_diagnosis_still_records_usage_spent(world):
    map_id, _, _ = _stall_map(world)
    failed = AgentCallFailed(reason="timeout", detail="LlmCallError(APITimeoutError)")
    gateway = FakeGateway(
        diagnose=lambda inp, call: failed,
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v1", tokens_in=500, tokens_out=80),
    )

    assert observe(world, map_id, gateway) == "model_failed"

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (LUNA, "diagnose-v1", 500, 80)


def test_diagnosis_and_its_structuring_carry_one_server_usage_label(world):
    """사용량 기록(llm_calls, #870)의 라벨 — 진단 왕복과 그 안의 ②(split 사전 비교)가 같은 trace의 agent_diagnose다. 서버 호출이라
    user_id가 없다."""
    from llm import usage

    map_id, _, _, _ = _split_map(world)
    seen: dict[str, usage.UsageLabel | None] = {}

    class Labelled(FakeGateway):
        def structure(self, raw):
            seen["structure"] = usage.current_label()
            return super().structure(raw)

    gateway = Labelled(diagnose=good_split, on_call=lambda what: seen.setdefault(what, usage.current_label()))
    assert observe(world, map_id, gateway) == "suggested"

    diagnose, structure = seen["diagnose"], seen["structure"]
    assert (diagnose.feature, diagnose.map_id, diagnose.user_id) == ("agent_diagnose", map_id, None)
    assert structure.trace_id == diagnose.trace_id
    assert usage.current_label() is None


def test_stub_and_code_only_runs_leave_usage_empty(world):
    stall_map, _, _ = _stall_map(world)
    gap_map = world.gap_map()
    world.event(gap_map)

    observe(world, stall_map, deps.FixedAgentLlmGateway())
    observe(world, gap_map, FakeGateway())

    for map_id in (stall_map, gap_map):
        run = world.one(AgentRun, map_id=map_id, trigger="activity")
        assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (None, None, 0, 0)


# ---------------------------------------------------------------- 모델을 부른 뒤의 예외 (#677)

def _failing_tool(*args, **kwargs):
    raise RuntimeError(f"DB 오류 {AGAINST_TEXT}")


def stall_then_failing_tool(inp, call_tool):
    call_tool("get_reasons", {"pin_ids": None, "category": inp["category"], "types": None})
    call_tool("get_readiness", {"category": inp["category"]})   # 여기서 예외
    raise AssertionError("도구 예외 뒤로는 오지 않는다")


def test_tool_error_after_the_model_call_is_recorded_and_counts_toward_the_cap(world, factory, monkeypatch):
    """진단 중 도구가 예외를 내면 error 행에 used_model=true, 그때까지의 사용량, 글 대신 글자 수인 도구 기록을 남긴다 —
    지도 상한에 센다. 같은 지도는 다음 tick에 다시 잡히지 않아 모델을 다시 부르지 않는다(#677)."""
    map_id, _, _ = _stall_map(world)
    monkeypatch.setitem(tools.TOOLS, "get_readiness", _failing_tool)
    gateway = FakeGateway(
        diagnose=stall_then_failing_tool,
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v2", tokens_in=900, tokens_out=200),
    )

    assert map_id in flows.run_tick(world.now, session_factory=world.factory, gateway=gateway)

    run = world.one(AgentRun, map_id=map_id)
    assert (run.trigger, run.outcome, run.used_model) == ("activity", "error", True)
    assert run.outcome_detail == {"stage": "model", "error": "ToolRunnerError"}
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (LUNA, "diagnose-v2", 900, 200)
    assert [c["name"] for c in run.tool_calls] == ["get_reasons"]
    assert run.tool_calls[0]["result"]["reasons"][0]["text_len"] == len(AGAINST_TEXT)
    assert AGAINST_TEXT not in _dump_agent_rows(factory)
    assert _model_runs_today(world, map_id) == 1

    assert map_id not in flows.run_tick(world.now + timedelta(minutes=5), session_factory=world.factory,
                                        gateway=gateway)
    assert gateway.calls == ["diagnose"]


def test_failure_after_saving_does_not_count_the_diagnosis_twice(world, monkeypatch):
    """요약 단계에서 실패하면 진단의 모델 사용은 이미 지도 관찰 행에 남았다 — error 행은 모델 사용 없이 남는다(#677)."""
    map_id, _, _ = _stall_map(world)
    monkeypatch.setattr(flows, "update_summary", _failing_tool)
    gateway = FakeGateway(
        diagnose=good_stall,
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v2", tokens_in=900, tokens_out=200),
    )

    flows.run_tick(world.now, session_factory=world.factory, gateway=gateway)

    runs = {r.outcome: r for r in world.rows(AgentRun, map_id=map_id)}
    assert set(runs) == {"suggested", "error"}
    assert (runs["suggested"].used_model, runs["suggested"].tokens_in) == (True, 900)
    assert (runs["error"].used_model, runs["error"].model, runs["error"].tokens_in) == (False, None, 0)
    assert runs["error"].outcome_detail == {"stage": "summary", "error": "RuntimeError"}
    assert _model_runs_today(world, map_id) == 1
    assert world.one(AgentSuggestion, map_id=map_id).status == "active"
    # 한 관찰에 지도 관찰 행과 error 행이 함께 있어도 예외로 끝난 관찰 하나로 센다 — 30분 뒤
    assert world.one(AgentCursor, map_id=map_id).next_check_at == world.now + timedelta(minutes=30)


def test_split_analysis_axis_names_come_from_recommend_labels(world):
    """축 이름은 recommend.api.fact_labels(#564). 🚫 칩 「좁아요」(spacious 원함)가 축 "넓은 곳" 쪽 이름으로 렌더된다."""
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    world.react(pin_id, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(pin_id, "u2", "like", hours_ago=25)
    world.react(pin_id, "u3", "against", hours_ago=20, text=AGAINST_TEXT, chips=["food_cramped"])
    world.event(map_id)

    assert observe(world, map_id, FakeGateway(diagnose=good_split)) == "suggested"

    with world.factory() as db:
        row = db.query(AgentSuggestion).filter_by(map_id=map_id).one()
        assert [k["fact_key"] for k in row.analysis["keys"]] == ["spacious"]
        rendered = flows._render(db, row)
    [axis] = rendered.analysis.axes
    assert axis.label == recommend_api.fact_labels()["spacious"]
    assert (axis.like_side, axis.against_side) == (None, "원함 1")


# ---------------------------------------------------------------- 노출: GET과 agent.suggested (#582)

@pytest.fixture()
def client(world):
    """사용자 이름을 받아 그 사람의 TestClient를 돌려준다(test_router.py와 같은 방식)."""
    from main import app

    def _db():
        with world.factory() as db, session_scope(db) as s:
            yield s

    app.dependency_overrides[get_db_session] = _db
    made = []

    def as_user(name: str) -> TestClient:
        c = TestClient(app, cookies=session_cookie(world.uid(name)))
        made.append(c)
        return c

    yield as_user
    for c in made:
        c.close()
    app.dependency_overrides.pop(get_db_session, None)


def test_split_suggestion_reaches_get_and_agent_suggested_with_analysis(world, client):
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    world.react(pin_id, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(pin_id, "u2", "like", hours_ago=25)
    world.react(pin_id, "u3", "against", hours_ago=20, text=AGAINST_TEXT, chips=["food_cramped"])
    world.event(map_id)

    assert observe(world, map_id, FakeGateway(diagnose=good_split)) == "suggested"

    [(type_, payload)] = suggestion_events(world, map_id)
    assert type_ == "agent.suggested"
    event = AgentSuggestionSchema.model_validate(payload)
    assert (event.diagnosis, event.category) == ("split", "음식점")
    assert event.analysis is not None and [a.label for a in event.analysis.axes] == [
        recommend_api.fact_labels()["spacious"]]
    state = client("u2").get(f"/maps/{map_id}/agent")
    assert state.status_code == 200
    active = state.json()["active_suggestion"]
    assert active == payload   # 응답과 이벤트는 같은 렌더(11절 끝)
    assert active["analysis"]["conflict_type"] == event.analysis.conflict_type
    assert state.json()["has_unseen"] is True


def test_stall_suggestion_reaches_get_and_agent_suggested(world, client):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, FakeGateway(diagnose=good_stall)) == "suggested"

    [(type_, payload)] = suggestion_events(world, map_id)
    assert (type_, payload["diagnosis"], payload["category"]) == ("agent.suggested", "stall", "음식점")
    assert payload["analysis"] is None
    assert [a["type"] for a in payload["actions"]] == ["open_recommend"]
    active = client("u1").get(f"/maps/{map_id}/agent").json()["active_suggestion"]
    assert active == payload

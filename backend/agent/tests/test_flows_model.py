"""관찰의 모델 단계(명세 12.4 5, 6단계, #533) — 우선순위, 진단, 검증, outcome, 모델 사용 집계.

17절 2(진단 부분), 7(모델 호출 중 상태가 바뀌면 stale), 11(Gateway 호출 중 열린 DB 세션 없음), 2절 13번(저장된 행에 사유
글 없음). Gateway는 이 파일의 대역(FakeGateway)이다 — 고정 응답 스텁(deps.FixedAgentLlmGateway)은 silent만 내서 저장
경로를 지나가지 않는다. 스텁 경로는 test_flows.py의 test_no_agent_row_contains_reason_text가 본다.
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from agent import deps, flows, tools
from agent.models import AgentRun, AgentSuggestion
from agent.schemas import AgentCallFailed, AgentReply, AgentUsage, DiagnosisOutput, PriorityItem, PriorityOutput
from agent.tests.world import World, fake_places, real_now
from llm import api as llm_api
from places import api as places_api
from recommend import api as recommend_api

LIKE_TEXT = "분위기가 아늑해서 오래 있기 좋아요"
AGAINST_TEXT = "주차할 곳이 전혀 없어서 힘들어요"


@pytest.fixture()
def factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


class FakeGateway:
    """Gateway 대역. diagnose는 llm.agent_diagnose처럼 call_id를 매겨 tool_runner를 부를 수 있게 call_tool을 넘긴다."""

    def __init__(self, diagnose=None, prioritize=None, on_call=None, priority_usage=None, diagnosis_usage=None):
        self._diagnose = diagnose
        self._prioritize = prioritize
        self.on_call = on_call or (lambda what: None)
        self._priority_usage = priority_usage or AgentUsage()
        self._diagnosis_usage = diagnosis_usage or AgentUsage()
        self.calls: list[str] = []
        self.inputs: list[dict] = []

    def prioritize(self, signals, principles):
        self.calls.append("prioritize")
        self.on_call("prioritize")
        if self._prioritize:
            return AgentReply(self._prioritize(signals), self._priority_usage)
        return AgentReply(PriorityOutput(order=[PriorityItem(signal_id=s["id"], reason="r") for s in signals]),
                          self._priority_usage)

    def diagnose(self, diagnosis_input, *, tool_runner):
        self.calls.append("diagnose")
        self.inputs.append(diagnosis_input)
        self.on_call("diagnose")
        counter = iter(range(1, 100))

        def call_tool(name, args):
            call_id = f"t{next(counter)}"
            return {"call_id": call_id, "result": tool_runner(call_id, name, args)}

        out = self._diagnose(diagnosis_input, call_tool) if self._diagnose else None
        self.on_call("diagnose_done")
        return AgentReply(out, self._diagnosis_usage)

    def structure(self, raw):
        return llm_api.plan_evidence(raw, planner=llm_api.passthrough_planner)


def observe(world, map_id, gateway):
    return flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway)


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


def split_first(signals):
    order = sorted(signals, key=lambda s: s["diagnosis"] != "split")
    return PriorityOutput(order=[PriorityItem(signal_id=s["id"], reason="r") for s in order])


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


# ---------------------------------------------------------------- 진단 → shadow 제안 (17절 2번 진단 부분)

def test_split_diagnosis_is_verified_and_saved_as_shadow(world, factory):
    map_id, pin_id, like, against = _split_map(world)
    gateway = FakeGateway(diagnose=good_split, prioritize=split_first)

    assert observe(world, map_id, gateway) == "suggested"

    assert gateway.calls == ["prioritize", "diagnose"]
    [inp] = gateway.inputs
    assert inp["pin_id"] == pin_id and inp["comparison"]["conflict_type"] == "unclear"   # dev ②는 키를 안 붙인다
    sug = world.one(AgentSuggestion, map_id=map_id)
    assert (sug.diagnosis, sug.shadow, sug.title, sug.pin_id is not None) == ("split", True, "의견이 갈린 핀이 있어요", True)
    assert {"id": "c3", "kind": "quote", "reaction_id": against} in sug.claims   # 인용은 id만
    assert sug.analysis == inp["comparison"]
    assert sug.actions == [{"index": 0, "type": "open_recommend", "label": "음식점 추천 받기",
                            "params": {"category": "음식점"}}]
    run = world.one(AgentRun, map_id=map_id)
    assert (run.outcome, run.used_model, run.priority["source"]) == ("suggested", True, "model")
    assert run.verification["established"] is True and run.verification["claims"]["removed"] == []
    assert [c["name"] for c in run.tool_calls] == ["get_reasons"]
    assert world.agent_events(map_id) == []   # 모델 유형은 shadow — 이벤트 없음(#534까지)
    dumped = _dump_agent_rows(factory)
    assert LIKE_TEXT not in dumped and AGAINST_TEXT not in dumped and AGAINST_TEXT[:8] not in dumped


def test_stall_diagnosis_uses_readiness_tool(world):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, FakeGateway(diagnose=good_stall)) == "suggested"

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert (sug.diagnosis, sug.category, sug.shadow) == ("stall", "음식점", True)
    run = world.one(AgentRun, map_id=map_id)
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

    run = world.one(AgentRun, map_id=map_id)
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
    assert world.one(AgentRun, map_id=map_id).verification == {"decision": decision}


def test_failed_verification_is_invalid_claims(world):
    map_id, _, _ = _stall_map(world)

    def made_up(inp, call):
        out = good_stall(inp, call)
        claim = out.claims[0].model_copy(update={"value": False})   # 도구 결과와 다른 값
        return out.model_copy(update={"claims": [claim]})

    assert observe(world, map_id, FakeGateway(diagnose=made_up)) == "invalid_claims"

    run = world.one(AgentRun, map_id=map_id)
    assert run.verification["claims"]["removed"] == [{"id": "c1", "reason": "tool_mismatch"}]
    assert run.verification["failed_step"] == 7
    assert run.outcome_detail == {"signal_id": "s1", "diagnosis": "stall", "decision": "suggest"}


def test_fixed_gateway_reads_reasons_and_stays_silent(world):
    map_id, _, _ = _stall_map(world)

    assert observe(world, map_id, deps.FixedAgentLlmGateway()) == "silent"

    run = world.one(AgentRun, map_id=map_id)
    assert [c["name"] for c in run.tool_calls] == ["get_reasons"] and run.used_model is True


# ---------------------------------------------------------------- 7. 모델 호출 중 상태가 바뀌면 stale

def test_pin_confirmed_during_diagnosis_makes_it_stale(world):
    map_id, pin_id, _, _ = _split_map(world)

    def confirm_during(what):
        if what == "diagnose":
            world.confirm(map_id, pin_id, hours_ago=0)   # 다른 연결에서 커밋

    gateway = FakeGateway(diagnose=good_split, prioritize=split_first, on_call=confirm_during)

    assert observe(world, map_id, gateway) == "stale"
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    assert world.one(AgentRun, map_id=map_id).used_model is True


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

    gateway = FakeGateway(diagnose=good_split, prioritize=split_first, on_call=check)

    assert observe(world, map_id, gateway) == "suggested"
    assert held == {"prioritize": 0, "diagnose": 0, "diagnose_done": 0}   # 도구가 연 세션도 닫혔다


# ---------------------------------------------------------------- 모델 사용 1회, 순위 재사용과 상한 (3절, 7절)

def test_prioritize_and_diagnose_count_as_one_model_use_and_order_is_reused(world):
    map_id, _, _, _ = _split_map(world)
    gateway = FakeGateway(diagnose=lambda inp, call: DiagnosisOutput(
        decision="silent", diagnosis=inp["diagnosis"], signal_id=inp["signal_id"], claims=[], advice=[], actions=[]))

    observe(world, map_id, gateway)
    observe(world, map_id, gateway)

    assert gateway.calls == ["prioritize", "diagnose", "diagnose"]   # 두 번째는 직전 순위를 다시 쓴다
    # 두 관찰의 started_at이 같아(world.now) 시각으로 순서를 가르지 않고 source로 찾는다
    runs = {r.priority["source"]: r for r in world.rows(AgentRun, map_id=map_id)}
    assert set(runs) == {"model", "reused"}
    assert runs["model"].used_model and runs["reused"].used_model
    assert runs["reused"].priority["final_order"] == runs["model"].priority["final_order"]
    with world.factory() as db:
        assert flows.service.load_history(db, map_id, world.now).model_runs_today == 2   # 관찰마다 1회


def test_model_cap_skips_priority_model_and_blocks_model_types(world, monkeypatch):
    map_id = world.gap_map()   # 코드 유형 신호 둘
    world.event(map_id)
    monkeypatch.setattr(flows.core, "PER_MEMBER_DAILY_MODEL_USES", 0)   # 상한 0 — 이미 도달
    gateway = FakeGateway()

    assert observe(world, map_id, gateway) == "suggested"

    assert gateway.calls == []
    run = world.one(AgentRun, map_id=map_id)
    assert (run.priority["source"], run.priority["fallback_reason"], run.used_model) == ("fallback", "model_cap", False)


def test_priority_failure_falls_back(world):
    map_id = world.gap_map()
    world.event(map_id)
    gateway = FakeGateway(prioritize=lambda signals: AgentCallFailed(reason="timeout", detail="x"))

    assert observe(world, map_id, gateway) == "suggested"

    run = world.one(AgentRun, map_id=map_id)
    assert (run.priority["source"], run.priority["fallback_reason"], run.used_model) == ("fallback", "timeout", True)


# ---------------------------------------------------------------- 사용량과 축 이름 (#564)

LUNA = "gpt-6-luna"


def test_usage_of_priority_and_diagnosis_is_summed_into_the_run(world):
    map_id, _, _, _ = _split_map(world)
    gateway = FakeGateway(
        diagnose=good_split, prioritize=split_first,
        priority_usage=AgentUsage(model=LUNA, prompt_version="prioritize-v1", tokens_in=120, tokens_out=30),
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v1", tokens_in=900, tokens_out=200),
    )

    assert observe(world, map_id, gateway) == "suggested"

    run = world.one(AgentRun, map_id=map_id)
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (
        LUNA, "prioritize-v1+diagnose-v1", 1020, 230,
    )


def test_failed_diagnosis_still_records_usage_spent(world):
    map_id, _, _ = _stall_map(world)
    failed = AgentCallFailed(reason="timeout", detail="LlmCallError(APITimeoutError)")
    gateway = FakeGateway(
        diagnose=lambda inp, call: failed,
        diagnosis_usage=AgentUsage(model=LUNA, prompt_version="diagnose-v1", tokens_in=500, tokens_out=80),
    )

    assert observe(world, map_id, gateway) == "model_failed"

    run = world.one(AgentRun, map_id=map_id)
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (LUNA, "diagnose-v1", 500, 80)


def test_failed_priority_usage_is_recorded_without_diagnosis(world):
    map_id = world.gap_map()   # 코드 유형 둘 — 진단은 부르지 않는다
    world.event(map_id)
    gateway = FakeGateway(
        prioritize=lambda signals: AgentCallFailed(reason="invalid_schema", detail="x"),
        priority_usage=AgentUsage(model=LUNA, prompt_version="prioritize-v1", tokens_in=70, tokens_out=0),
    )

    assert observe(world, map_id, gateway) == "suggested"

    run = world.one(AgentRun, map_id=map_id)
    assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (LUNA, "prioritize-v1", 70, 0)


def test_stub_and_code_only_runs_leave_usage_empty(world):
    stall_map, _, _ = _stall_map(world)
    gap_map = world.gap_map()
    world.event(gap_map)

    observe(world, stall_map, deps.FixedAgentLlmGateway())
    observe(world, gap_map, FakeGateway())   # 상한 안이라 우선순위는 부르지만 대역의 사용량은 0

    for map_id in (stall_map, gap_map):
        run = world.one(AgentRun, map_id=map_id)
        assert (run.model, run.prompt_version, run.tokens_in, run.tokens_out) == (None, None, 0, 0)


def test_split_analysis_axis_names_come_from_recommend_labels(world):
    """축 이름은 recommend.api.fact_labels(#564). 🚫 칩 「좁아요」(spacious 원함)가 축 "넓은 곳" 쪽 이름으로 렌더된다."""
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    world.react(pin_id, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(pin_id, "u2", "like", hours_ago=25)
    world.react(pin_id, "u3", "against", hours_ago=20, text=AGAINST_TEXT, chips=["food_cramped"])
    world.event(map_id)

    assert observe(world, map_id, FakeGateway(diagnose=good_split, prioritize=split_first)) == "suggested"

    with world.factory() as db:
        row = db.query(AgentSuggestion).filter_by(map_id=map_id).one()
        assert [k["fact_key"] for k in row.analysis["keys"]] == ["spacious"]
        rendered = flows._render(db, row)
    [axis] = rendered.analysis.axes
    assert axis.label == recommend_api.fact_labels()["spacious"]
    assert (axis.like_side, axis.against_side) == (None, "원함 1")

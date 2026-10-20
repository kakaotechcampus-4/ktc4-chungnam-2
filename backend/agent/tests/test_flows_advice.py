"""추천 막힘 조언을 끝까지(명세 9절, 17절 2·11·12·13, #587) — 실제 DB, 실제 recommend.api(run 조회와 시뮬레이션), llm의 도구
왕복(agent_advise_run)을 지나간다. 모델 자리에는 이 파일의 대본(planner)이 들어가 도구를 부르고 claim을 쓴다.

run은 recommend 모듈 테스트(test_run_reads_api.py)와 같은 판이다: 카페 반경 1000m, 장소 다섯(ok, 붐빔, 좁음, 반경 밖, 이미
제안), 근거 줄 셋(다른 구성원의 「붐빔」, 요청자 본인의 「넓은 곳」, 요청자 본인의 조건 없는 글). 실행하면 결과는 ok 한 곳이라
조언 대상이다. 장소 검색과 라벨은 recommend.deps를 대역으로 바꾼다.
"""

import json
import threading
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import select

from agent import deps, flows, service
from agent.models import AgentRun, AgentRunAdvice
from agent.schemas import Action, AdviceLine, AgentCallFailed, AgentReply, AgentUsage, RunAdviceOutput, ToolClaim
from agent.tests.world import World, real_now
from auth.testing import ensure_users, session_cookie
from common.database import get_db_session, session_scope
from common.errors import AppError
from llm import api as llm_api
from places.schemas import FactLabel
from recommend import api as recommend_api
from recommend import deps as recommend_deps
from recommend import flows as recommend_flows
from recommend import service as recommend_service
from recommend.models import RecommendRun, Region
from recommend.ports import PlaceStub

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))

NAMES = {"u1": "김철수", "u2": "이영희"}
OWN_TEXT = "비밀근거_좁아서 다리를 펼 수가 없었어요"
OTHER_TEXT = "비밀근거_사람이 너무 많아서 정신없었어요"
VAGUE_TEXT = "비밀근거_그냥 그래요"
SECRETS = (OWN_TEXT, OTHER_TEXT, VAGUE_TEXT, *NAMES.values())

PLACES = [
    PlaceStub(place_id="ok", lat=35.0005, lng=129.0005),
    PlaceStub(place_id="crowded", lat=35.0004, lng=129.0005),
    PlaceStub(place_id="narrow", lat=35.0005, lng=129.0004),
    PlaceStub(place_id="far", lat=35.0135, lng=129.0),   # 약 1500m — 반경 배율 2배에서만 들어온다
    PlaceStub(place_id="proposed", lat=35.0006, lng=129.0006),
]
MORE = [PlaceStub(place_id=f"ok{i}", lat=35.0003, lng=129.0003) for i in (2, 3)]
FACTS = {
    "ok": {"is_crowded_large": False, "spacious": True}, "ok2": {"is_crowded_large": False, "spacious": True},
    "ok3": {"is_crowded_large": False, "spacious": True}, "crowded": {"is_crowded_large": True, "spacious": True},
    "narrow": {"is_crowded_large": False, "spacious": False}, "far": {"is_crowded_large": False, "spacious": True},
    "proposed": {"is_crowded_large": False, "spacious": True},
}


class FakePlaceSearch:
    def __init__(self, places):
        self.places = places

    def search_nearby(self, *, category, circles):
        return self.places

    def get_names(self, place_ids):
        return {}


class FakePlaceFacts:
    def get_facts(self, place_ids):
        return {pid: [FactLabel(k, v, "known") for k, v in FACTS.get(pid, {}).items()] for pid in place_ids}


@pytest.fixture()
def places(monkeypatch):
    search = FakePlaceSearch(list(PLACES))
    monkeypatch.setattr(recommend_deps, "get_place_search_gateway", lambda: search)
    monkeypatch.setattr(recommend_deps, "get_place_facts_gateway", lambda: FakePlaceFacts())
    return search


@pytest.fixture()
def world(factory, places):
    w = World(factory, real_now())
    yield w
    w.cleanup()


@pytest.fixture()
def map_id(world):
    found = world.map(members=("u1", "u2"))
    with world.factory() as db:
        ensure_users(db, *(world.uid(u) for u in NAMES), display_names={world.uid(u): n for u, n in NAMES.items()})
        db.commit()
    return found


def make_run(world, map_id, *, execute=True, walk=15, requester="u1") -> str:
    """조언 대상 판. execute=False면 근거 수집 중인 run이다."""
    with world.factory() as db:
        run = RecommendRun(map_id=map_id, category="카페", requested_by=world.uid(requester),
                           status="collecting_evidence", default_radius_walk_min=walk)
        db.add(run)
        db.flush()
        db.add(Region(run_id=run.id, signature="sig", label="기본 반경", center_lat=35.0, center_lng=129.0,
                      radius_m=1000, anchor_points=[[35.0, 129.0]], confirmed=True))
        line = {"source": "reaction", "badge": "required"}
        recommend_service.add_reaction_evidence(db, run_id=run.id, lines=[
            line | {"author_id": world.uid("u2"), "text": OTHER_TEXT, "fact_key": "is_crowded_large", "wants": None},
            line | {"author_id": world.uid(requester), "text": OWN_TEXT, "fact_key": "spacious", "wants": True},
            line | {"author_id": world.uid(requester), "text": VAGUE_TEXT},
        ])
        recommend_service.add_exclusions(db, map_id=map_id, category="카페", place_ids=["proposed"], reason="proposed",
                                         run_id=run.id, requested_by=world.uid(requester))
        if execute:
            recommend_flows.execute_run(db, run_id=str(run.id), place_search=recommend_deps.get_place_search_gateway(),
                                        place_facts=recommend_deps.get_place_facts_gateway())
        db.commit()
        return str(run.id)


# ---------------------------------------------------------------- 모델 대역

def tc(cid, called, path):
    """도구 결과(call_tool의 반환값)에서 그 경로의 값 그대로 claim을 만든다 — 진짜 모델이 옮겨 적는 것과 같다."""
    value = called["result"]
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return ToolClaim(id=cid, kind="tool_result", call_id=called["call_id"], path=path, value=value)


def soft_relax(advice_input, call_tool):
    evidence = call_tool("get_run_evidence", {})
    lines = evidence["result"]["lines"]
    own = next(i for i, line in enumerate(lines) if line["author"] == "본인" and line["kind"] == "condition")
    other = next(i for i, line in enumerate(lines) if line["author"] == "다른 구성원")
    own_sim = call_tool("simulate_filter", {"radius_factor": None, "disable_line_ids": [lines[own]["line_id"]]})
    other_sim = call_tool("simulate_filter", {"radius_factor": None, "disable_line_ids": [lines[other]["line_id"]]})
    return RunAdviceOutput(
        decision="suggest", kind="soft_relax",
        claims=[tc("c1", own_sim, "gained"), tc("c2", evidence, f"lines.{own}.label"),
                tc("c3", other_sim, "gained"), tc("c4", evidence, f"lines.{other}.label")],
        advice=[
            AdviceLine(text="「{c2.value}」 조건을 끄면 {c1.value}곳이 더 남아요", basis=["c1", "c2"], is_guess=False),
            AdviceLine(text="다른 구성원의 「{c4.value}」 조건 때문에 {c3.value}곳이 빠졌어요", basis=["c3", "c4"],
                       is_guess=False),
            AdviceLine(text="김철수 님이 정한 조건이에요 {c1.value}", basis=["c1"], is_guess=False),   # 이름 — 빠진다
        ],
        actions=[Action(type="open_evidence", basis=["c1"]), Action(type="open_evidence", basis=["c3"])],
    )


def radius(advice_input, call_tool):
    """상한 밖(3배), 상한까지, 버튼 한 번(next_radius_factor, #677) 셋을 시뮬레이션하고 셋 모두에 버튼을 붙인다."""
    over = call_tool("simulate_filter", {"radius_factor": 3.0, "disable_line_ids": None})
    to_limit = call_tool("simulate_filter", {"radius_factor": advice_input["radius"]["max_radius_factor"],
                                             "disable_line_ids": None})
    one_press = call_tool("simulate_filter", {"radius_factor": advice_input["radius"]["next_radius_factor"],
                                              "disable_line_ids": None})
    return RunAdviceOutput(
        decision="suggest", kind="radius",
        claims=[tc("c1", over, "gained"), tc("c2", to_limit, "gained"), tc("c3", one_press, "gained")],
        advice=[AdviceLine(text="반경을 끝까지 넓히면 {c2.value}곳이 더 나와요", basis=["c2"], is_guess=False),
                AdviceLine(text="더 멀리 가면 {c1.value}곳이에요", basis=["c1"], is_guess=False)],
        actions=[Action(type="widen_radius", basis=["c1"]), Action(type="widen_radius", basis=["c2"]),
                 Action(type="widen_radius", basis=["c3"])],
    )


def exhausted(advice_input, call_tool):
    stage = next(i for i, e in enumerate(advice_input["funnel"]["result"]["funnel"]) if e["label"] == "이미 제안·거절됨")
    claim = ToolClaim(id="c1", kind="tool_result", call_id="t0", path=f"funnel.{stage}.removed_count",
                      value=advice_input["funnel"]["result"]["funnel"][stage]["removed_count"])
    return RunAdviceOutput(
        decision="suggest", kind="exhausted", claims=[claim],
        advice=[AdviceLine(text="이미 보여 드렸거나 거절한 곳이 {c1.value}곳 빠졌어요", basis=["c1"], is_guess=False)],
        actions=[],
    )


class ScriptedGateway(deps.FixedAgentLlmGateway):
    """advise_run만 대본으로 — llm.agent_advise_run을 그대로 지나가 call_id와 도구 상한은 진짜와 같다."""

    def __init__(self, script, before=None):
        self.script = script
        self.before = before or (lambda: None)
        self.inputs: list[dict] = []

    def advise_run(self, advice_input, *, tool_runner):
        self.inputs.append(advice_input)
        self.before()
        return llm_api.agent_advise_run(advice_input, tool_runner=tool_runner, planner=self.script)


class FailingGateway(deps.FixedAgentLlmGateway):
    def advise_run(self, advice_input, *, tool_runner):
        return AgentReply(AgentCallFailed(reason="timeout", detail="APITimeoutError(APITimeoutError)"), AgentUsage())


class ForbiddenGateway(deps.FixedAgentLlmGateway):
    def advise_run(self, advice_input, *, tool_runner):
        raise AssertionError("모델을 다시 부르면 안 된다")


def advise(world, run_id, gateway, requester="u1"):
    return flows.advise_run(run_id, world.uid(requester), session_factory=world.factory, gateway=gateway)


def advice_rows(world, run_id):
    return world.rows(AgentRunAdvice, run_id=uuid.UUID(run_id))


def advice_runs(world, map_id):
    return world.rows(AgentRun, map_id=map_id, trigger="run_advice")


def _dump(rows, *cols) -> str:
    return json.dumps([{c: getattr(r, c) for c in cols} for r in rows], ensure_ascii=False, default=str)


# ---------------------------------------------------------------- soft_relax (17절 2)

def test_soft_relax_button_only_for_own_line_and_nothing_private_is_said_or_stored(world, map_id):
    run_id = make_run(world, map_id)
    labels = recommend_api.fact_labels()

    advice = advise(world, run_id, ScriptedGateway(soft_relax))

    own_line = next(line for line in recommend_service_lines(world, run_id) if line["text"] == OWN_TEXT)
    assert advice.kind == "soft_relax"
    assert [a.text for a in advice.advice] == [
        f"「{labels['spacious']} 원함」 조건을 끄면 1곳이 더 남아요",
        f"다른 구성원의 「{labels['is_crowded_large']}」 조건 때문에 1곳이 빠졌어요",
    ]
    assert [a.model_dump(mode="json") for a in advice.actions] == [{
        "index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
        "params": {"run_id": run_id, "evidence_line_ids": [own_line["line_id"]]},
    }]
    body = advice.model_dump_json()
    stored = _dump(advice_rows(world, run_id), "kind", "claims", "advice", "actions")
    logged = _dump(advice_runs(world, map_id), "tool_calls", "verification", "outcome_detail")
    for secret in (*SECRETS, world.uid("u1"), world.uid("u2")):
        assert secret not in body
        assert secret not in stored
        assert secret not in logged   # 도구 기록의 근거 글은 글자 수로 바뀐다(2절 13번)
    assert "text_len" in logged


def recommend_service_lines(world, run_id):
    with world.factory() as db:
        return recommend_api.get_run_evidence(db, run_id=run_id)


def test_advice_is_logged_as_run_advice_and_not_counted_in_the_map_cap(world, map_id):
    run_id = make_run(world, map_id)

    advise(world, run_id, ScriptedGateway(soft_relax))

    [row] = advice_runs(world, map_id)
    assert (row.trigger, row.outcome, row.used_model) == ("run_advice", "advised", True)
    assert row.outcome_detail == {"run_id": run_id, "stored": True, "decision": "suggest", "kind": "soft_relax"}
    assert [c["call_id"] for c in row.tool_calls] == ["t0", "t1", "t2", "t3"]   # 깔때기(t0)는 코드가 미리 읽었다
    assert row.tool_calls[0]["prefetched"] is True
    assert advice_rows(world, run_id)[0].agent_run_id == row.id
    with world.factory() as db:
        assert service.load_history(db, map_id, world.now).model_runs_today == 0   # 9절: 지도 상한에 세지 않는다


def test_the_model_input_has_the_funnel_and_no_people(world, map_id):
    run_id = make_run(world, map_id)
    gateway = ScriptedGateway(exhausted)

    advice = advise(world, run_id, gateway)

    [sent] = gateway.inputs
    assert sent["funnel"]["call_id"] == "t0" and sent["result_count"] == 1
    assert sent["radius"] == {"walk_min": 15, "max_walk_min": 30, "max_radius_factor": 2.0,
                              "next_radius_factor": 20 / 15}
    assert all(s not in json.dumps(sent, ensure_ascii=False) for s in (*SECRETS, world.uid("u1"), map_id))
    assert [a.text for a in advice.advice] == ["이미 보여 드렸거나 거절한 곳이 1곳 빠졌어요"]


# ---------------------------------------------------------------- 반경 상한 (가드레일 4)

def test_widen_beyond_the_limit_is_dropped(world, map_id):
    """상한 밖 시뮬레이션은 claim부터 빠지고, 상한까지 넓힌 숫자는 문장으로만 남는다 — 버튼은 한 번에 5분만 넓혀서 버튼은
    한 번 넓힌 시뮬레이션에만 붙는다(#677)."""
    run_id = make_run(world, map_id)

    advice = advise(world, run_id, ScriptedGateway(radius))

    assert [a.text for a in advice.advice] == ["반경을 끝까지 넓히면 1곳이 더 나와요"]
    assert [a.model_dump(mode="json") for a in advice.actions] == [
        {"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": run_id}},
    ]
    [row] = advice_runs(world, map_id)
    assert {"id": "c1", "reason": "radius_over_limit"} in row.verification["claims"]["removed"]
    assert row.verification["actions"]["removed"] == [{"index": 0, "reason": "basis"},
                                                      {"index": 1, "reason": "not_next_step"}]
    [one_press] = [c for c in row.tool_calls if c["args"].get("radius_factor") == 20 / 15]
    assert one_press["result"]["gained"] == 0   # 이 판은 원이 1000m라 × 20/15 = 1333m, 약 1500m의 far는 아직 밖이다


def test_no_widen_when_the_run_is_already_at_the_limit(world, map_id):
    run_id = make_run(world, map_id, walk=30)

    advice = advise(world, run_id, ScriptedGateway(radius))   # 배율 1.0도 상한 안이지만 넓힌 것이 아니다

    assert advice is None
    assert advice_rows(world, run_id)[0].kind is None


# ---------------------------------------------------------------- run당 1회 (17절 13)

def test_second_request_returns_the_stored_advice_without_the_model(world, map_id):
    run_id = make_run(world, map_id)
    first = advise(world, run_id, ScriptedGateway(soft_relax))

    second = advise(world, run_id, ForbiddenGateway())

    assert second == first
    assert len(advice_runs(world, map_id)) == 1


def test_concurrent_requests_store_one_advice_and_return_the_same(world, map_id):
    run_id = make_run(world, map_id)
    both_in = threading.Barrier(2, timeout=10)   # 두 요청이 모두 "저장된 것 없음"을 본 뒤 모델 단계에 들어간다
    results, errors = [], []

    def call():
        try:
            results.append(advise(world, run_id, ScriptedGateway(soft_relax, before=both_in.wait)))
        except Exception as exc:  # noqa: BLE001 — 스레드 밖에서 실패로 보인다
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(results) == 2 and results[0] == results[1] and results[0] is not None
    assert len(advice_rows(world, run_id)) == 1
    logged = advice_runs(world, map_id)
    assert sorted(r.outcome_detail["stored"] for r in logged) == [False, True]   # 늦은 쪽은 저장하지 않았다
    assert advice_rows(world, run_id)[0].agent_run_id == next(r.id for r in logged if r.outcome_detail["stored"])


# ---------------------------------------------------------------- 대상 아님, 침묵, 실패

def test_not_a_target_writes_nothing(world, map_id, places):
    places.places = PLACES + MORE   # 결과 3곳, 같은 카테고리 run 1개
    run_id = make_run(world, map_id)

    assert advise(world, run_id, ForbiddenGateway()) is None
    assert advice_rows(world, run_id) == [] and advice_runs(world, map_id) == []


def test_three_runs_in_the_same_category_make_a_target(world, map_id, places):
    places.places = PLACES + MORE
    runs = [make_run(world, map_id) for _ in range(3)]

    assert advise(world, runs[1], ForbiddenGateway()) is None   # 두 번째 run까지는 2개 — 나중 run은 세지 않는다
    assert advise(world, runs[2], ScriptedGateway(exhausted)) is not None


def test_unfinished_run_is_not_a_target(world, map_id):
    run_id = make_run(world, map_id, execute=False)

    assert advise(world, run_id, ForbiddenGateway()) is None
    assert advice_rows(world, run_id) == []


def test_silent_stub_is_stored_empty_and_never_asked_again(world, map_id):
    run_id = make_run(world, map_id)

    assert advise(world, run_id, deps.FixedAgentLlmGateway()) is None   # 고정 응답 스텁은 늘 silent
    [row] = advice_rows(world, run_id)
    assert (row.kind, row.claims, row.advice, row.actions) == (None, [], [], [])
    assert advice_runs(world, map_id)[0].outcome == "silent"
    assert advise(world, run_id, ForbiddenGateway()) is None


def test_model_failure_is_stored_empty_without_retry(world, map_id):
    run_id = make_run(world, map_id)

    assert advise(world, run_id, FailingGateway()) is None

    [logged] = advice_runs(world, map_id)
    assert (logged.outcome, logged.outcome_detail["reason"]) == ("model_failed", "timeout")
    assert advice_rows(world, run_id)[0].kind is None
    assert advise(world, run_id, ForbiddenGateway()) is None


# ---------------------------------------------------------------- 우리 쪽 예외 (#677, 16.5)

LUNA = "gpt-6-luna"


def _boom(*args, **kwargs):
    raise RuntimeError(f"예외 메시지 {OWN_TEXT}")


class ToolFailingGateway(deps.FixedAgentLlmGateway):
    """도구가 예외를 낸 llm처럼 — 그때까지 쓴 사용량을 붙인 ToolRunnerError를 올린다(llm.service.agent_advise_run)."""

    def advise_run(self, advice_input, *, tool_runner):
        exc = llm_api.ToolRunnerError("tool_runner 실패: simulate_filter OperationalError")
        exc.usage = AgentUsage(model=LUNA, prompt_version="advise-v1", tokens_in=700, tokens_out=50)
        raise exc


@pytest.mark.parametrize("stage", ["prefetch", "model", "verify"])
def test_exception_is_logged_as_error_and_the_next_request_tries_again(world, map_id, monkeypatch, stage):
    """미리 읽기, 도구, 검증이 예외를 내면 error 행만 남기고 조언은 저장하지 않는다(None → 204). 다음 요청이 다시 만든다(16.5).
    outcome_detail은 run과 단계와 예외 클래스 이름뿐이다 — 예외 메시지는 남기지 않는다."""
    run_id = make_run(world, map_id)
    target = {"prefetch": (recommend_api, "get_run_funnel"), "model": (recommend_api, "simulate_filter"),
              "verify": (flows.core, "verify_run_advice")}[stage]
    with monkeypatch.context() as m:
        m.setattr(*target, _boom)
        assert advise(world, run_id, ScriptedGateway(radius)) is None

    assert advice_rows(world, run_id) == []
    [row] = advice_runs(world, map_id)
    assert (row.outcome, row.used_model) == ("error", stage != "prefetch")
    error = "ToolRunnerError" if stage == "model" else "RuntimeError"   # 도구 예외는 llm이 감싸 올린다
    assert row.outcome_detail == {"run_id": run_id, "stage": stage, "error": error}
    assert "예외 메시지" not in _dump([row], "tool_calls", "outcome_detail")
    assert OWN_TEXT not in _dump([row], "tool_calls", "outcome_detail")

    again = advise(world, run_id, ScriptedGateway(radius))
    assert again is not None and again.kind == "radius"
    assert sorted(r.outcome for r in advice_runs(world, map_id)) == ["advised", "error"]


def test_tool_error_keeps_the_usage_spent_so_far(world, map_id):
    run_id = make_run(world, map_id)

    assert advise(world, run_id, ToolFailingGateway()) is None

    [row] = advice_runs(world, map_id)
    assert (row.outcome, row.used_model) == ("error", True)
    assert (row.model, row.prompt_version, row.tokens_in, row.tokens_out) == (LUNA, "advise-v1", 700, 50)
    assert [c["name"] for c in row.tool_calls] == ["get_run_funnel"]   # 미리 읽은 깔때기(t0)
    with world.factory() as db:
        assert service.load_history(db, map_id, world.now).model_runs_today == 0   # 조언은 지도 상한에 세지 않는다(9절)


def test_only_the_requester_and_only_existing_runs(world, map_id):
    run_id = make_run(world, map_id)

    with pytest.raises(AppError) as forbidden:
        advise(world, run_id, ForbiddenGateway(), requester="u2")
    with pytest.raises(AppError) as missing:
        advise(world, str(uuid.uuid4()), ForbiddenGateway())

    assert (forbidden.value.code, missing.value.code) == ("FORBIDDEN", "NOT_FOUND")


# ---------------------------------------------------------------- 세션 (12.6, 17절 11)

def test_no_db_connection_is_held_while_the_model_runs(world, map_id, test_engine):
    run_id = make_run(world, map_id)
    held = []
    gateway = ScriptedGateway(soft_relax, before=lambda: held.append(test_engine.pool.checkedout()))

    advise(world, run_id, gateway)

    assert held == [0]


# ---------------------------------------------------------------- 라우터 GET /runs/{runId}/advice (17절 12)

@pytest.fixture()
def client(world, monkeypatch):
    from main import app

    def _db():
        with world.factory() as db, session_scope(db) as s:
            yield s

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[deps.get_session_factory] = lambda: world.factory
    made = []

    def as_user(name: str) -> TestClient:
        c = TestClient(app, cookies=session_cookie(world.uid(name)))
        made.append(c)
        return c

    yield as_user
    for c in made:
        c.close()
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(deps.get_session_factory, None)


def _spec_errors(name: str, body) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:pingo-spec#/components/schemas/{name}"}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)]


def test_router_permissions_and_204(world, map_id, client, places, monkeypatch):
    monkeypatch.setattr(deps, "get_llm_gateway", lambda: ForbiddenGateway())
    with world.factory() as db:
        ensure_users(db, world.uid("outsider"))
        db.commit()
    world.user_ids.add(world.uid("outsider"))
    places.places = PLACES + MORE
    not_target = make_run(world, map_id)

    assert client("outsider").get(f"/runs/{not_target}/advice").status_code == 404   # 비구성원은 존재를 모른다
    assert client("u2").get(f"/runs/{not_target}/advice").status_code == 403         # 구성원이지만 요청자가 아니다
    assert client("u1").get(f"/runs/{uuid.uuid4()}/advice").status_code == 404
    empty = client("u1").get(f"/runs/{not_target}/advice")
    assert (empty.status_code, empty.content) == (204, b"")


def test_router_answers_204_not_500_when_the_advice_fails(world, map_id, client, monkeypatch):
    """조언 실패는 추천 결과 화면을 깨지 않는다 — 204로 끝나고 저장하지 않아 다시 열면 다시 부른다(16.5, #677)."""
    run_id = make_run(world, map_id)
    monkeypatch.setattr(deps, "get_llm_gateway", lambda: ToolFailingGateway())

    r = client("u1").get(f"/runs/{run_id}/advice")

    assert (r.status_code, r.content) == (204, b"")
    assert advice_rows(world, run_id) == []
    monkeypatch.setattr(deps, "get_llm_gateway", lambda: ScriptedGateway(exhausted))
    assert client("u1").get(f"/runs/{run_id}/advice").status_code == 200


def test_router_returns_the_spec_shape_and_releases_the_request_session(world, map_id, client, test_engine,
                                                                       monkeypatch):
    run_id = make_run(world, map_id)
    held = []
    gateway = ScriptedGateway(soft_relax, before=lambda: held.append(test_engine.pool.checkedout()))
    monkeypatch.setattr(deps, "get_llm_gateway", lambda: gateway)

    first = client("u1").get(f"/runs/{run_id}/advice")
    again = client("u1").get(f"/runs/{run_id}/advice")

    assert first.status_code == 200 and _spec_errors("RunAdvice", first.json()) == []
    assert again.json() == first.json() and len(gateway.inputs) == 1
    assert held == [0]   # 인증과 권한을 확인한 요청 세션도 모델 호출 전에 연결을 돌려줬다
    assert all(s not in first.text for s in SECRETS)


def test_advice_row_keeps_the_map_for_purge(world, map_id):
    run_id = make_run(world, map_id)
    advise(world, run_id, ScriptedGateway(exhausted))

    with world.factory() as db:
        assert db.execute(select(AgentRunAdvice.map_id).where(AgentRunAdvice.run_id == uuid.UUID(run_id))).scalar_one() == map_id

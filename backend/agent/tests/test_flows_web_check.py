"""웹 확인을 관찰부터 응답까지(명세 6.8, #1216) — 실제 DB, 실제 pins·recommend api. 장소와 라벨은 places 대역, 웹 확인은 Gateway 대역.

- 「모름」인 줄 모두(많아야 2줄)를 동시에 확인한다(#1317). 값이 참·거짓이면 부르지 않는다
- 모델 입력은 장소 이름·동네·특징 이름뿐이다(구성원 글, 이름, 별칭, 지도 id 없음). 부를 때 열린 DB 세션이 없다
- 저장은 facts 항목의 web {status, statements[{text, source_url}], checked_at}. failed는 저장하지 않고 제안은 그대로 나간다
- 렌더 때 값이 지금도 unknown일 때만 web을 낸다. not_found·paused는 서버 고정 문구(notice)
- 같은 지도에서 24시간 안의 found·not_found는 다시 쓰고, paused와 24시간 지난 것은 다시 부른다
- 도구 기록 w1, w2(줄 순서, status와 문장 수만), 도구 상한과 지도 하루 상한에 세지 않는다
"""

import json
from datetime import datetime, timedelta

import pytest

from agent import core, flows, service, tools
from agent.models import AgentRun, AgentSuggestion
from agent.tests import rows
from agent.tests.test_flows_facts import Gateway, _dump, _stall_map, observe, suggested
from agent.tests.test_flows_facts import AGAINST_TEXT, LIVE_TEXT, PLACE_NAME
from agent.tests.test_flows_model import client, good_stall  # noqa: F401 — client는 픽스처
from agent.tests.test_flows_status import _spec_errors
from agent.tests.world import World, real_now
from llm import api as llm_api
from llm import usage as llm_usage
from places import api as places_api
from places.schemas import FactLabel, PlaceInfo
from recommend import api as recommend_api

ADDRESS = "서울특별시 성동구 성수이로 1 (성수동2가)"
AREA = "성동구 성수동2가"
BLOG = "https://blog.example.com/p/1"
KEYS = {AGAINST_TEXT: [("parking_available", True)], LIVE_TEXT: [("parking_available", True)]}
FOUND = llm_api.WebCheckResult(status="found", statements=(
    llm_api.VerifiedStatement(text="가게 앞에 두세 대 댈 수 있다고 적혀 있어요", source_url=BLOG, source_name="blog.example.com"),
), web_searches=1)


@pytest.fixture()
def labels(monkeypatch):
    table: dict[str, dict[str, tuple]] = {}

    def get_facts(place_ids, *, db=None):
        return {pid: [FactLabel(k, v, c) for k, (v, c) in table.get(pid, {}).items()] for pid in place_ids}

    monkeypatch.setattr(places_api, "get_facts", get_facts)
    return table


@pytest.fixture()
def world(factory, monkeypatch, labels):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)

    def get_places(place_ids, *, db=None):
        return {pid: PlaceInfo(pid, PLACE_NAME, 37.5, 127.0, "음식점", address=ADDRESS) for pid in place_ids if pid == "pl_food"}

    monkeypatch.setattr(places_api, "get_places", get_places)
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


class WebGateway(Gateway):
    """진단·②는 test_flows_facts의 대역, 웹 확인은 정해 둔 결과. 부를 때의 입력, 라벨, 열린 DB 연결 수를 남긴다."""

    def __init__(self, result=FOUND, *, engine=None):
        super().__init__(good_stall, KEYS)
        self.result, self.engine = result, engine
        self.web_inputs: list[dict] = []

    def web_check(self, *, place_name, area, feature, forbidden):
        label = llm_usage.current_label()
        self.web_inputs.append({
            "place_name": place_name, "area": area, "feature": feature, "forbidden": tuple(forbidden),
            "feature_label": label.feature if label else None, "map_id": label.map_id if label else None,
            "held": self.engine.pool.checkedout() if self.engine is not None else None,
        })
        return self.result


def _stored_web(world, map_id):
    [fact] = world.one(AgentSuggestion, map_id=map_id).facts
    return fact.get("web")


def _w1(world, map_id):
    [run] = [r for r in world.rows(AgentRun, map_id=map_id) if r.trigger != "summary" and r.trigger != "status"]
    return [c for c in run.tool_calls if c["call_id"] == "w1"]


# ---------------------------------------------------------------- 찾았다

def test_found_is_saved_rendered_and_matches_spec(world, labels, client, test_engine):
    map_id, food = _stall_map(world)
    gateway = WebGateway(engine=test_engine)

    assert observe(world, map_id, gateway) == "suggested"

    [called] = gateway.web_inputs
    assert {k: called[k] for k in ("place_name", "area", "feature")} == {
        "place_name": PLACE_NAME, "area": AREA, "feature": "주차 가능"}
    assert called["forbidden"] == core.WEB_CHECK_FORBIDDEN
    assert (called["feature_label"], called["map_id"]) == ("agent_web_check", map_id)   # llm_calls 라벨(#870)
    assert called["held"] == 0                                                          # 2절 6번

    web = _stored_web(world, map_id)
    assert web["status"] == "found" and web["statements"] == [{"text": FOUND.statements[0].text, "source_url": BLOG}]
    assert datetime.fromisoformat(web["checked_at"]) == world.now   # 관찰 시각

    [line] = suggested(world, map_id)["facts"]
    assert line["web"] == {"status": "found", "notice": None, "checked_at": line["web"]["checked_at"], "statements": [
        {"text": FOUND.statements[0].text, "source_url": BLOG, "source_name": "blog.example.com"}]}
    assert _spec_errors("AgentSuggestion", suggested(world, map_id)) == []
    state = client("u1").get(f"/maps/{map_id}/agent").json()
    assert state["active_suggestion"]["facts"][0]["web"] == line["web"]

    labels["pl_food"] = {"parking_available": (True, "known")}   # 라벨이 생기면 우리 데이터가 앞선다 — web을 내지 않는다
    [line] = client("u1").get(f"/maps/{map_id}/agent").json()["active_suggestion"]["facts"]
    assert line["value"] == "yes" and "web" not in line


def test_model_input_has_no_member_text_names_or_map_id(world):
    map_id, _ = _stall_map(world)
    gateway = WebGateway()

    observe(world, map_id, gateway)

    sent = json.dumps({k: v for k, v in gateway.web_inputs[0].items() if k in ("place_name", "area", "feature")},
                      ensure_ascii=False)
    for secret in (AGAINST_TEXT, LIVE_TEXT, map_id, world.uid("u1"), world.uid("u2"), "m1", "m2"):
        assert secret not in sent


def test_tool_record_w1_has_only_status_and_count(world, factory):
    map_id, food = _stall_map(world)

    observe(world, map_id, WebGateway())

    [w1] = _w1(world, map_id)
    assert (w1["name"], w1["args"]) == ("web_check", {"pin_id": food, "fact_key": "parking_available"})
    assert w1["result"]["status"] == "found" and w1["result"]["statements"] == 1 and w1["result"]["reused"] is False
    dumped = json.dumps(w1, ensure_ascii=False)
    assert BLOG not in dumped and FOUND.statements[0].text not in dumped and PLACE_NAME not in dumped
    assert PLACE_NAME not in _dump(factory) and AGAINST_TEXT not in _dump(factory)   # 2절 13번은 그대로


def test_web_check_is_not_counted_against_tool_or_daily_limits(world):
    """w1은 모델이 고르지 않는다 — 진단 도구 기록(t1 …)과 따로이고 지도 하루 상한의 관찰 수도 늘지 않는다(6.8)."""
    map_id, _ = _stall_map(world)

    observe(world, map_id, WebGateway())

    [run] = [r for r in world.rows(AgentRun, map_id=map_id) if r.trigger not in ("summary", "status")]
    model_tools = [c for c in run.tool_calls if c["call_id"].startswith("t")]
    assert [c["name"] for c in model_tools] == ["get_readiness"]
    with world.factory() as db:
        assert service.load_history(db, map_id, world.now).model_runs_today == 1   # 진단 관찰 1번뿐


# ---------------------------------------------------------------- 찾지 못함, 쉼, 실패

@pytest.mark.parametrize("status, notice", [
    ("not_found", "웹에서도 찾지 못했어요"),
    ("paused", "오늘은 웹 확인을 쉬고 있어요. 내일 다시 찾아볼게요"),
])
def test_not_found_and_paused_carry_the_server_notice(world, status, notice):
    map_id, _ = _stall_map(world)

    observe(world, map_id, WebGateway(llm_api.WebCheckResult(status=status)))

    assert _stored_web(world, map_id)["status"] == status
    [line] = suggested(world, map_id)["facts"]
    assert (line["web"]["status"], line["web"]["notice"], line["web"]["statements"]) == (status, notice, [])
    assert _spec_errors("AgentFactLine", line) == []


def test_failed_is_not_saved_and_the_suggestion_still_goes_out(world):
    map_id, _ = _stall_map(world)

    assert observe(world, map_id, WebGateway(llm_api.WebCheckResult(status="failed", detail="timeout:x"))) == "suggested"

    assert _stored_web(world, map_id) is None
    [line] = suggested(world, map_id)["facts"]
    assert line["value"] == "unknown" and "web" not in line
    assert _w1(world, map_id)[0]["result"]["status"] == "failed"


def test_known_label_is_not_checked(world, labels):
    map_id, _ = _stall_map(world)
    labels["pl_food"] = {"parking_available": (False, "known")}
    gateway = WebGateway()

    observe(world, map_id, gateway)

    assert gateway.web_inputs == [] and _stored_web(world, map_id) is None and _w1(world, map_id) == []


def test_fixed_gateway_never_says_not_found(world):
    """dev 스텁은 웹을 찾지 않는다 — 「웹에서도 찾지 못했어요」를 내지 않고 칸도 저장도 없다(#1221). 기록 w1에는 failed로 남는다."""
    map_id, _ = _stall_map(world)

    assert observe(world, map_id, Gateway(good_stall, KEYS)) == "suggested"

    assert _stored_web(world, map_id) is None
    [line] = suggested(world, map_id)["facts"]
    assert "web" not in line
    assert _w1(world, map_id)[0]["result"]["status"] == "failed"


def test_real_budget_gate_pauses_through_the_fixed_gateway(world, monkeypatch):
    """예산은 llm이 본다 — agent는 따로 계산하지 않는다. 고정 응답 스텁 Gateway로도 예산을 넘으면 paused가 된다."""
    map_id, _ = _stall_map(world)
    monkeypatch.setattr(llm_usage, "spent_reader", lambda since: 10_000.0)

    observe(world, map_id, Gateway(good_stall, KEYS))

    assert _stored_web(world, map_id)["status"] == "paused"


# ---------------------------------------------------------------- 24시간 재사용

def _earlier(world, map_id, pin_id, web, *, hours_ago):
    with world.factory() as db:
        rows.suggestion(db, map_id, status="dismissed", diagnosis="stall", category="음식점",
                        facts=[{"pin_id": pin_id, "fact_key": "parking_available", "web": web}],
                        created_at=world.now - timedelta(hours=hours_ago), expires_at=world.now)
        db.commit()


def _web(status, *, hours_ago, world):
    statements = [{"text": "예전에 찾은 문장이에요", "source_url": BLOG}] if status == "found" else []
    return {"status": status, "statements": statements, "checked_at": (world.now - timedelta(hours=hours_ago)).isoformat()}


@pytest.mark.parametrize("status", ["found", "not_found"])
def test_recent_result_is_reused_without_calling(world, status):
    map_id, food = _stall_map(world)
    earlier = _web(status, hours_ago=2, world=world)
    _earlier(world, map_id, food, earlier, hours_ago=2)
    gateway = WebGateway()

    observe(world, map_id, gateway)

    assert gateway.web_inputs == []
    [active] = [s for s in world.rows(AgentSuggestion, map_id=map_id) if s.status == "active"]
    assert active.facts[0]["web"] == earlier
    assert _w1(world, map_id)[0]["result"]["reused"] is True


@pytest.mark.parametrize("status, hours_ago", [("paused", 1), ("found", 25)])
def test_paused_or_old_results_are_checked_again(world, status, hours_ago):
    map_id, food = _stall_map(world)
    _earlier(world, map_id, food, _web(status, hours_ago=hours_ago, world=world), hours_ago=hours_ago)
    gateway = WebGateway()

    observe(world, map_id, gateway)

    assert len(gateway.web_inputs) == 1
    [active] = [s for s in world.rows(AgentSuggestion, map_id=map_id) if s.status == "active"]
    assert active.facts[0]["web"]["status"] == "found"


def test_other_maps_results_are_not_reused(world):
    map_id, food = _stall_map(world)
    other = world.map()
    _earlier(world, other, food, _web("found", hours_ago=1, world=world), hours_ago=1)
    gateway = WebGateway()

    observe(world, map_id, gateway)

    assert len(gateway.web_inputs) == 1


# ---------------------------------------------------------------- 「모름」 두 줄(#1317)

QUIET = recommend_api.fact_labels()["quiet"]   # 특징 이름은 코드 표가 정한다
KEYS_TWO = {AGAINST_TEXT: [("parking_available", True), ("quiet", True)], LIVE_TEXT: [("parking_available", True)]}


class TwoLineGateway(WebGateway):
    """🚫 사유가 두 키(주차, 조용함)를 말해 우리 데이터 줄이 두 개다. 웹 확인 결과는 특징 이름마다 정해 둔다."""

    def __init__(self, results=None, **kw):
        super().__init__(**kw)
        self.keys = KEYS_TWO
        self.results = results or {}

    def web_check(self, *, place_name, area, feature, forbidden):
        super().web_check(place_name=place_name, area=area, feature=feature, forbidden=forbidden)
        return self.results.get(feature, FOUND)


def _web_calls(world, map_id):
    [run] = [r for r in world.rows(AgentRun, map_id=map_id) if r.trigger not in ("summary", "status")]
    return [c for c in run.tool_calls if c["call_id"].startswith("w")]


def test_two_unknown_lines_are_both_checked_and_logged_as_w1_w2(world, test_engine):
    map_id, food = _stall_map(world)
    not_found = llm_api.WebCheckResult(status="not_found")
    gateway = TwoLineGateway({QUIET: not_found}, engine=test_engine)

    assert observe(world, map_id, gateway) == "suggested"

    assert sorted(c["feature"] for c in gateway.web_inputs) == sorted([QUIET, "주차 가능"])
    assert all(c["feature_label"] == "agent_web_check" and c["map_id"] == map_id for c in gateway.web_inputs)   # 스레드에도 라벨
    assert all(c["held"] == 0 for c in gateway.web_inputs)
    stored = world.one(AgentSuggestion, map_id=map_id).facts
    assert [(f["fact_key"], f["web"]["status"]) for f in stored] == [("parking_available", "found"), ("quiet", "not_found")]
    calls = _web_calls(world, map_id)
    assert [(c["call_id"], c["args"]) for c in calls] == [
        ("w1", {"pin_id": food, "fact_key": "parking_available"}), ("w2", {"pin_id": food, "fact_key": "quiet"})]
    assert [c["result"]["status"] for c in calls] == ["found", "not_found"]
    lines = suggested(world, map_id)["facts"]
    assert [line["web"]["status"] for line in lines] == ["found", "not_found"]
    steps = [st for st in suggested(world, map_id)["steps"] if st["stage"] == "웹 확인"]
    assert len(steps) == 2   # 작업 기록도 줄마다 하나


def test_one_unknown_line_of_two_is_checked_once(world, labels):
    map_id, _ = _stall_map(world)
    labels["pl_food"] = {"quiet": (True, "known")}
    gateway = TwoLineGateway()

    observe(world, map_id, gateway)

    assert [c["feature"] for c in gateway.web_inputs] == ["주차 가능"]
    assert [c["call_id"] for c in _web_calls(world, map_id)] == ["w1"]


def test_reuse_is_decided_per_line(world):
    """한 줄은 24시간 안의 결과를 다시 쓰고, 다른 줄만 부른다."""
    map_id, food = _stall_map(world)
    earlier = _web("not_found", hours_ago=2, world=world)
    _earlier(world, map_id, food, earlier, hours_ago=2)   # parking_available만 예전에 확인했다
    gateway = TwoLineGateway()

    observe(world, map_id, gateway)

    assert [c["feature"] for c in gateway.web_inputs] == [QUIET]
    [active] = [s for s in world.rows(AgentSuggestion, map_id=map_id) if s.status == "active"]
    assert active.facts[0]["web"] == earlier and active.facts[1]["web"]["status"] == "found"
    assert [(c["call_id"], c["result"]["reused"]) for c in _web_calls(world, map_id)] == [("w1", True), ("w2", False)]


def test_two_checks_run_at_the_same_time(world):
    """두 호출은 동시에 간다 — 한쪽이 다른 쪽을 기다리는 장벽을 둘 다 넘으면 동시에 돈 것이다(차례로 돌면 장벽에서 시간이 다 된다)."""
    import threading
    map_id, _ = _stall_map(world)
    barrier = threading.Barrier(2, timeout=5)

    class Together(TwoLineGateway):
        def web_check(self, **kw):
            barrier.wait()
            return super().web_check(**kw)

    gateway = Together()
    observe(world, map_id, gateway)

    assert len(gateway.web_inputs) == 2 and not barrier.broken

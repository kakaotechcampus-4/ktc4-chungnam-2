"""우리 데이터 확인을 관찰부터 응답까지(명세 6.6, #1168) — 실제 DB, 실제 pins·recommend api. 장소 이름과 라벨은 places 대역.

- 진단이 검증을 통과한 갈림·정체 제안에만 붙는다. 갈림은 사실 다툼(같은 키·같은 방향)일 때만, 취향 다툼이면 비어 있다
- 저장은 (pin_id, fact_key)만이고 agent.suggested와 GET은 그때의 라벨로 렌더한다 — 라벨이 바뀌면 GET이 바뀐다
- 실시간 핀은 빠진다. ②가 실패해도 제안은 나가고 이 칸만 빈다
- 저장된 어떤 행에도 사유 글, 장소 이름, 라벨 값이 없다(2절 13번)
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from agent import deps, flows, tools
from agent.models import AgentSuggestion
from agent.schemas import AgentSuggestion as AgentSuggestionSchema
from agent.tests.test_flows_model import AGAINST_TEXT, LIKE_TEXT, client, good_split, good_stall  # noqa: F401 — client는 픽스처
from agent.tests.test_flows_status import _spec_errors
from agent.tests.world import World, fake_places, real_now
from llm import api as llm_api
from llm.service import PlanEvidenceFailed
from places import api as places_api
from places.schemas import FactLabel

PLACE_NAME = "성수 칼국수"
LIVE_QUERY = "비밀검색어_을지로 노포"
LIVE_TEXT = "비밀사유_차 댈 데가 없어요"


@pytest.fixture()
def labels(monkeypatch):
    """places.api.get_facts 대역 — place_id → {키: (값, confidence)}. 테스트가 고치면 다음 렌더에 바로 보인다."""
    table: dict[str, dict[str, tuple]] = {}

    def get_facts(place_ids, *, db=None):
        return {pid: [FactLabel(k, v, c) for k, (v, c) in table.get(pid, {}).items()] for pid in place_ids}

    monkeypatch.setattr(places_api, "get_facts", get_facts)
    return table


@pytest.fixture()
def world(factory, monkeypatch, labels):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({"pl_food": PLACE_NAME}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


class Gateway(deps.FixedAgentLlmGateway):
    """진단은 정해 둔 함수, ②는 글마다 정해 둔 (키, 방향), 현황 문단은 고정 응답 스텁."""

    def __init__(self, diagnose, keys, *, fail_structure_after=None):
        self._diagnose = diagnose
        self.keys = keys
        self.structured = 0
        self.fail_structure_after = fail_structure_after

    def diagnose(self, diagnosis_input, *, tool_runner):
        counter = iter(range(1, 100))

        def call_tool(name, args):
            call_id = f"t{next(counter)}"
            return {"call_id": call_id, "result": tool_runner(call_id, name, args)}

        return llm_api.AgentReply(self._diagnose(diagnosis_input, call_tool), llm_api.AgentUsage())

    def structure(self, raw):
        self.structured += 1
        if self.fail_structure_after is not None and self.structured > self.fail_structure_after:
            raise PlanEvidenceFailed("timeout")
        return [
            [llm_api.EvidenceLine(source="reaction", text=r["text"], badge=r["badge"], fact_key=k, wants=w)
             for k, w in self.keys.get(r["text"], ())]
            or [llm_api.EvidenceLine(source="reaction", text=r["text"], badge=r["badge"])]
            for r in raw
        ]


def observe(world, map_id, gateway):
    return flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway)


def suggested(world, map_id) -> dict:
    [payload] = [p for t, p in world.agent_events(map_id) if t == "agent.suggested"]
    return payload


def _split_map(world):
    map_id = world.map()
    pin_id = world.pin(map_id, place_id="pl_food", hours_ago=100)
    world.react(pin_id, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(pin_id, "u2", "like", hours_ago=25)
    world.react(pin_id, "u3", "against", hours_ago=20, text=AGAINST_TEXT)
    world.event(map_id)
    return map_id, pin_id


def _dump(factory) -> str:
    with factory() as db:
        return json.dumps([db.execute(text(f"SELECT row_to_json(t)::text FROM {t} t")).scalars().all()
                           for t in ("agent_suggestions", "agent_runs")], ensure_ascii=False)


# ---------------------------------------------------------------- 갈림: 사실 다툼

def test_split_fact_dispute_is_saved_as_ids_and_rendered_from_current_label(world, labels, client, factory):
    """♥ 「분위기가 아늑해서…」와 🚫 「주차할 곳이…」가 둘 다 주차 가능을 원한다(같은 키·같은 방향) — 가게가 주차되는지가 쟁점이다."""
    map_id, pin_id = _split_map(world)
    labels["pl_food"] = {"parking_available": (False, "known")}
    gateway = Gateway(good_split, {LIKE_TEXT: [("parking_available", True)], AGAINST_TEXT: [("parking_available", True)]})

    assert observe(world, map_id, gateway) == "suggested"

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert sug.facts == [{"pin_id": pin_id, "fact_key": "parking_available"}]   # 값과 이름은 저장하지 않는다
    payload = suggested(world, map_id)
    [line] = payload["facts"]
    assert (line["fact_key"], line["value"]) == ("parking_available", "no")
    assert [s["kind"] for s in line["segments"]] == ["text", "pin", "text"]
    assert "".join(s["text"] for s in line["segments"]) == (
        f"우리 데이터: {PLACE_NAME}는 주차 가능이 아니라고 나와요. 데이터가 틀릴 수 있어요")
    assert _spec_errors("AgentSuggestion", payload) == []

    state = client("u1").get(f"/maps/{map_id}/agent").json()
    assert state["active_suggestion"]["facts"] == payload["facts"]

    labels["pl_food"] = {"parking_available": (True, "known")}   # 라벨이 바뀌면 같은 제안의 화면도 바뀐다
    [line] = client("u1").get(f"/maps/{map_id}/agent").json()["active_suggestion"]["facts"]
    assert (line["value"], line["segments"][2]["text"]) == ("yes", "는 주차 가능으로 나와요")
    labels["pl_food"] = {}                                        # 라벨이 없으면 모름
    [line] = client("u1").get(f"/maps/{map_id}/agent").json()["active_suggestion"]["facts"]
    assert line["value"] == "unknown"

    dumped = _dump(factory)
    assert LIKE_TEXT not in dumped and AGAINST_TEXT not in dumped and PLACE_NAME not in dumped


def test_split_taste_dispute_has_no_fact_lines(world):
    """방향이 반대(♥ 원함, 🚫 피함)면 취향이 갈린 것이다 — 데이터로 풀 일이 아니라 칸을 붙이지 않는다."""
    map_id, _ = _split_map(world)
    gateway = Gateway(good_split, {LIKE_TEXT: [("quiet", True)], AGAINST_TEXT: [("quiet", False)]})

    assert observe(world, map_id, gateway) == "suggested"

    assert world.one(AgentSuggestion, map_id=map_id).facts == []
    assert suggested(world, map_id)["facts"] == []


# ---------------------------------------------------------------- 정체: 반대 사유의 키, 실시간 핀 제외

def _stall_map(world):
    map_id = world.map()
    food = world.pin(map_id, place_id="pl_food", hours_ago=100)
    live = world.live_pin(map_id, LIVE_QUERY, hours_ago=100)
    world.react(food, "u2", "against", hours_ago=21, text=AGAINST_TEXT)
    world.react(live, "u3", "against", hours_ago=20, text=LIVE_TEXT)
    world.event(map_id)
    return map_id, food


def test_stall_gets_fact_lines_from_against_reasons_without_live_pins(world, labels):
    map_id, food = _stall_map(world)
    keys = {AGAINST_TEXT: [("parking_available", True)], LIVE_TEXT: [("parking_available", True)]}

    assert observe(world, map_id, Gateway(good_stall, keys)) == "suggested"

    [stored] = world.one(AgentSuggestion, map_id=map_id).facts
    assert (stored["pin_id"], stored["fact_key"]) == (food, "parking_available")
    [line] = suggested(world, map_id)["facts"]
    assert line["value"] == "unknown" and line["segments"][1]["pin_id"] == food
    assert line["web"]["status"] == "not_found"   # 「모름」 줄은 웹 확인(6.8) 대상이다. dev 스텁은 늘 not_found(test_flows_web_check.py)
    assert LIVE_QUERY not in json.dumps(suggested(world, map_id), ensure_ascii=False)


def test_structure_failure_drops_only_the_fact_lines(world):
    """우리 데이터 확인의 ②가 실패해도 진단이 낸 제안은 나간다 — 이 칸만 빈다."""
    map_id, _ = _stall_map(world)
    # 진단 도구(get_readiness)는 ②를 부르지 않는다. 처음 부르는 ②가 우리 데이터 확인의 것이다
    gateway = Gateway(good_stall, {AGAINST_TEXT: [("parking_available", True)]}, fail_structure_after=0)

    assert observe(world, map_id, gateway) == "suggested"

    assert world.one(AgentSuggestion, map_id=map_id).facts == []
    assert suggested(world, map_id)["facts"] == []


def test_code_type_suggestions_have_no_fact_lines(world):
    map_id = world.gap_map()
    world.event(map_id)

    assert observe(world, map_id, deps.FixedAgentLlmGateway()) == "suggested"

    assert world.one(AgentSuggestion, map_id=map_id).facts == []
    assert suggested(world, map_id)["facts"] == []


# ---------------------------------------------------------------- 계약 — 값 세 가지가 스펙과 같다

@pytest.mark.parametrize("value", ["yes", "no", "unknown"])
def test_fact_line_value_matches_spec(value):
    """AgentFactLine.value의 enum은 따옴표가 있어야 파이썬 계약 검사(PyYAML, YAML 1.1)가 yes/no를 참거짓이 아니라 문자열로
    읽는다(#1179에서 고침, #1168 보고)."""
    line = {"fact_key": "quiet", "value": value, "segments": [{"kind": "text", "text": "우리 데이터로는 "}]}
    assert _spec_errors("AgentFactLine", line) == []

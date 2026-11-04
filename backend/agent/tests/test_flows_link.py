"""AI 추천·AI 코스와 엮기(명세 6.10, #1357) — 실제 DB로 도는 도구와 관찰.

- try_in_schedule 도구: AI 코스의 일정 입력(read_snapshot, read_pins, build_input)과 places 영업으로 끼워 본다. 확정 핀·없는 핀은
  not_found, 실시간 핀은 no_coords, 결과와 도구 기록에 장소 이름·검색어가 없다
- e2e: 카테고리 공백(후보 핀 있음) → 모델이 try_in_schedule → open_pin. llm이 그 유형을 아직 모르면(#1358 전) 템플릿
- e2e: 일정 점검 → open_course 템플릿(모델 없음) → 수락 → 사람이 일정을 고치면 problem_gone

places는 대역이다(좌표와 영업을 정해 둔다). llm의 유형별 도구 목록과 출력 스키마는 #1358이 category_gap·try_in_schedule·open_pin을
더한다 — 그 전이라 DIAGNOSIS_TOOLS는 monkeypatch로 넣고 진단 출력은 model_construct로 만든다.
"""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import update

from agent import core, flows, snapshot, tools
from agent.models import AgentRun, AgentSuggestion
from agent.schemas import Action, AdviceLine, DiagnosisOutput, RefClaim, ToolClaim
from agent.tests.test_flows_model import FakeGateway
from agent.tests.world import World, real_now
from common.database import session_scope
from llm import api as llm_api
from places import api as places_api
from places.schemas import PlaceInfo
from shortlist.models import ShortlistItem

NAME = "장소이름"            # 장소 이름 앞머리 — 도구 결과, 기록, 모델 입력 어디에도 나오면 안 된다
LIVE_QUERY = "실시간카페검색어"
GAP_TOOLS = ("get_reasons", "try_in_schedule", "get_readiness")
COORDS = {   # place_id → (lat, lng). 음식점 둘은 첫날, 카페 c1은 그 근처
    "pl_f1": (37.5665, 126.978), "pl_f2": (37.5685, 126.978), "pl_t1": (37.5705, 126.978),
    "pl_c1": (37.5675, 126.979), "pl_c2": (37.6100, 127.050),
    **{f"pl_x{i}": (37.56 + i * 0.001, 126.98) for i in range(7)},
}


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    w.week = {}   # place_id → 요일 → 영업(places.api.get_week_open_status 대역)

    def get_places(place_ids, *, db=None):
        return {pid: PlaceInfo(pid, f"{NAME}_{pid}", *COORDS[pid], "음식점") for pid in place_ids if pid in COORDS}

    monkeypatch.setattr(places_api, "get_places", get_places)
    monkeypatch.setattr(places_api, "get_week_open_status",
                        lambda place_ids, *, db=None: {p: w.week[p] for p in place_ids if p in w.week})
    monkeypatch.setattr(places_api, "get_open_status_on_weekdays", lambda place_ids, weekdays, *, db=None: {})
    yield w
    w.cleanup()


def _schedule(world, map_id, pin_id, day_offset, order):
    with world.factory() as db:
        db.execute(update(ShortlistItem).where(ShortlistItem.map_id == map_id, ShortlistItem.pin_id == uuid.UUID(pin_id))
                   .values(scheduled_date=world.today + timedelta(days=30 + day_offset), visit_order=order))
        db.commit()


def _gap_map(world):
    """음식점 확정 2곳을 첫날에 넣은 지도. 카페 후보는 c1(db, ♥ u2)과 실시간 핀. 관광지는 핀이 없다."""
    map_id = world.map()
    f1, f2 = world.pin(map_id, place_id="pl_f1"), world.pin(map_id, place_id="pl_f2")
    for i, f in enumerate((f1, f2), start=1):
        world.confirm(map_id, f)
        _schedule(world, map_id, f, 0, i)
    c1 = world.pin(map_id, category="카페", place_id="pl_c1", hours_ago=90)
    live = world.live_pin(map_id, LIVE_QUERY, category="카페", hours_ago=80)
    world.react(c1, "u2", "like", hours_ago=10)
    world.event(map_id)
    return map_id, f1, c1, live


def _ctx(world, map_id):
    with world.factory() as db:
        snap = snapshot.build(db, map_id, world.now)
    return tools.ToolContext(map_id=map_id, snap=snap, allowed=GAP_TOOLS, session_factory=world.factory,
                             structure=lambda raw: [], now=world.now, cache=tools.StructureCache())


# ---------------------------------------------------------------- 도구

def test_try_in_schedule_fits_open_pins_and_keeps_names_out(world):
    map_id, f1, c1, live = _gap_map(world)
    start = world.today + timedelta(days=30)
    world.week = {"pl_c1": {start.weekday(): "closed"}}
    ctx = _ctx(world, map_id)

    result = ctx.run("t1", "try_in_schedule", {"pin_ids": [c1, live, f1, "없는핀"]})

    rows = {r["pin_id"]: r for r in result["pins"]}
    assert rows[c1]["day"] == "d1" and isinstance(rows[c1]["added_minutes"], int)
    assert (rows[c1]["open"], rows[c1]["fills_gap"]) == ("closed", True)
    assert rows[live] == {"pin_id": live, "no_coords": True}
    assert result["not_found"] == [f1, "없는핀"]          # 확정한 핀과 지도에 없는 핀
    raw = json.dumps([result, ctx.calls], ensure_ascii=False, default=str)
    assert NAME not in raw and LIVE_QUERY not in raw


def test_try_in_schedule_takes_at_most_five_pins(world):
    map_id = world.map()
    pins = [world.pin(map_id, category="카페", place_id=f"pl_x{i}") for i in range(7)]
    ctx = _ctx(world, map_id)
    result = ctx.run("t1", "try_in_schedule", {"pin_ids": pins})
    assert [r["pin_id"] for r in result["pins"]] == pins[:5]
    # 일정과 확정 장소가 없으면 숫자를 지어내지 않는다
    assert all((r["day"], r["added_minutes"], r["nearest_minutes"]) == (None, None, None) for r in result["pins"])


# ---------------------------------------------------------------- 카테고리 공백 → try_in_schedule → open_pin

def _open_pin_diagnosis(c1):
    def diagnose(inp, call_tool):
        fit = call_tool("try_in_schedule", {"pin_ids": [c["pin_id"] for c in inp["candidates"]]})
        rows = fit["result"]["pins"]
        i = next(k for k, r in enumerate(rows) if r["pin_id"] == c1)
        return DiagnosisOutput.model_construct(
            decision="suggest", diagnosis="category_gap", signal_id=inp["signal_id"],
            claims=[ToolClaim(id="c1", kind="tool_result", call_id=fit["call_id"], path=f"pins.{i}.added_minutes",
                              value=rows[i]["added_minutes"]),
                    RefClaim(id="c2", kind="ref", object="pin", ref_id=c1)],
            advice=[AdviceLine(text="{c2}은 첫날 동선에 넣으면 이동이 {c1.value}분 늘어요", basis=["c1", "c2"], is_guess=False)],
            actions=[Action.model_construct(type="open_pin", category=None, pin_ids=[c1], basis=["c1"])],
        )
    return diagnose


def test_category_gap_with_candidates_tries_the_schedule_and_opens_the_pin(world, monkeypatch):
    monkeypatch.setitem(llm_api.DIAGNOSIS_TOOLS, "category_gap", GAP_TOOLS)
    map_id, _, c1, live = _gap_map(world)
    world.week = {"pl_c1": {d: "open" for d in range(7)}}
    gateway = FakeGateway(diagnose=_open_pin_diagnosis(c1))

    assert flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway) == "suggested"

    assert gateway.calls == ["diagnose"]
    inp = gateway.inputs[0]
    assert (inp["diagnosis"], inp["category"]) == ("category_gap", "카페")
    assert {c["pin_id"] for c in inp["candidates"]} == {c1, live}
    row = world.one(AgentSuggestion, map_id=map_id)
    assert (row.diagnosis, row.category) == ("category_gap", "카페")
    assert [(a["type"], a["params"]["pin_ids"]) for a in row.actions] == [("open_pin", [c1])]
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.used_model is True
    assert [c["name"] for c in run.tool_calls if c["call_id"].startswith("t")] == ["try_in_schedule"]
    stored = json.dumps([run.tool_calls, run.signals, row.claims, row.advice, inp], ensure_ascii=False, default=str)
    assert NAME not in stored and LIVE_QUERY not in stored

    with world.factory() as db:
        rendered = flows._render(db, db.get(AgentSuggestion, row.id))
    assert rendered.actions[0].label == "이 핀 보기"
    assert "AI 코스 엔진으로 핀 2개를 일정에 끼워 봤어요" in [st.text for st in rendered.steps]


def test_category_gap_stays_a_template_until_llm_knows_the_type(world):
    if "category_gap" in llm_api.DIAGNOSIS_TOOLS:
        pytest.skip("#1358이 llm에 category_gap을 더했다 — 이 경로는 없어졌다")
    map_id, *_ = _gap_map(world)
    gateway = FakeGateway()

    assert flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway) == "suggested"

    assert gateway.calls == []
    row = world.one(AgentSuggestion, map_id=map_id)
    assert (row.diagnosis, row.category, [a["type"] for a in row.actions]) == ("category_gap", "카페", ["open_recommend"])


# ---------------------------------------------------------------- 일정 점검 → open_course → 풀림

def _schedule_map(world):
    """음식점·카페·관광지를 하나씩 확정해 첫날에 넣은 지도(카테고리 공백 없음)."""
    map_id = world.map()
    pins = [world.pin(map_id, category=c, place_id=p) for c, p in (("음식점", "pl_f1"), ("카페", "pl_c1"), ("관광지", "pl_t1"))]
    for i, p in enumerate(pins, start=1):
        world.confirm(map_id, p)
        _schedule(world, map_id, p, 0, i)
    world.event(map_id)
    return map_id, pins


def test_schedule_problem_suggests_the_course_and_is_resolved_when_fixed(world):
    map_id, pins = _schedule_map(world)
    weekday = (world.today + timedelta(days=30)).weekday()
    world.week = {"pl_f1": {weekday: "closed"}, "pl_c1": {weekday: "open"}, "pl_t1": {weekday: "open"}}
    gateway = FakeGateway()

    assert flows.observe_map(map_id, world.now, session_factory=world.factory, gateway=gateway) == "suggested"

    assert gateway.calls == []                       # 코드 유형 — 모델을 부르지 않는다
    row = world.one(AgentSuggestion, map_id=map_id)
    assert (row.diagnosis, row.category, row.title) == ("schedule", None, "일정에 다시 볼 곳이 있어요")
    assert [(a["type"], a["label"]) for a in row.actions] == [("open_course", "AI 코스로 고칠 안 받기")]
    with world.factory() as db:
        rendered = flows._render(db, db.get(AgentSuggestion, row.id))
    assert [seg.kind for seg in rendered.advice[0].segments] == ["text", "pin"]
    assert rendered.advice[0].segments[1].pin_id == pins[0]

    with world.factory() as db, session_scope(db) as s:
        flows.accept(s, row=s.get(AgentSuggestion, row.id), action_index=0, user_id=world.uid("u2"), now=world.now)
    world.week["pl_f1"] = {weekday: "open"}          # 사람이 그날 여는 곳으로 고쳤다(영업 판정이 바뀐 것과 같다)
    world.event(map_id, seconds_ago=5)
    flows.observe_map(map_id, world.now + timedelta(minutes=1), session_factory=world.factory, gateway=gateway)

    with world.factory() as db:
        done = db.get(AgentSuggestion, row.id)
        assert (done.status, done.followup["status"], done.followup["reason"]) == ("accepted", "resolved", "problem_gone")
    assert core.DECIDED_DIAGNOSES.count("schedule") == 0

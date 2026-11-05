"""후속 관찰과 충돌 선언의 흐름(명세 6.9, #1346) — 관찰(observe_map), 수락(accept), 상태(get_state)를 DB와 함께.

- 수락 → 다른 카테고리 활동 → 후속(다음 방법, 진단을 해 본 것과 함께) → 수락 → 충돌 선언(코드, 모델 없음)
- 새 핀이 올라오면 풀림, 지켜보는 줄(tracking)
- 저장 직전 재확인에서 풀렸으면 stale
- run 결과(비공개)는 진단 입력, 저장, 화면 어디에도 없다
"""

import json
from datetime import timedelta

import pytest

from agent import flows, tools
from agent.models import AgentRun, AgentSuggestion
from agent.schemas import DiagnosisOutput
from agent.tests.test_flows_model import AGAINST_TEXT, FakeGateway, good_stall
from agent.tests.world import World, fake_places, real_now
from common.database import session_scope
from places import api as places_api
from recommend.models import Candidate, RecommendRun

SECRET = "비밀런"


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


def next_method(inp, call_tool):
    """다음 방법을 쓰는 모델 — 해 본 것과 허용 행동을 보고, 숫자는 f1을 가리킨다."""
    return DiagnosisOutput.model_validate({
        "decision": "suggest", "diagnosis": "stall", "signal_id": inp["signal_id"],
        "claims": [{"id": "c1", "kind": "tool_result", "call_id": "f1", "path": "new_pins", "value": 0}],
        "advice": [{"text": "추천 받기를 해 봤지만 새 후보가 {c1.value}곳 지도에 올랐어요", "basis": ["c1"], "is_guess": False},
                   {"text": "직접 찾아서 올려 보면 좋겠어요", "basis": ["c1"], "is_guess": True}],
        "actions": [{"type": "open_recommend", "category": None, "pin_ids": None, "basis": ["c1"]},
                    {"type": "search_place", "category": None, "pin_ids": None, "basis": ["c1"]}],
    })


def _stall_world(world):
    """음식점 핀에 🚫(20시간 전), 카페 핀 둘(30분 전)은 다른 카테고리 활동용."""
    map_id = world.map()
    food = world.pin(map_id, hours_ago=100)
    cafes = [world.pin(map_id, category="카페", hours_ago=0.5) for _ in range(2)]   # 최근 핀 — 반응 공백 대상이 아직 아니다
    world.react(food, "u2", "against", hours_ago=20, text=AGAINST_TEXT)
    world.event(map_id)
    return map_id, food, cafes


def _observe(world, map_id, gateway, at):
    return flows.observe_map(map_id, at, session_factory=world.factory, gateway=gateway)


def _active(world, map_id):
    rows = world.rows(AgentSuggestion, map_id=map_id)
    return next((r for r in rows if r.status == "active"), None)


def _accept(world, row, at, index=0):
    with world.factory() as db, session_scope(db) as s:
        return flows.accept(s, row=s.get(AgentSuggestion, row.id), action_index=index, user_id=world.uid("u1"), now=at)


def _state(world, map_id, at):
    with world.factory() as db:
        return flows.get_state(db, map_id=map_id, user_id=world.uid("u1"), now=at)


def _run(world, map_id, at):
    """누군가 「추천 받기」를 눌렀다 — 비공개 run. 결과는 에이전트가 쓰면 안 된다."""
    with world.factory() as db:
        run = RecommendRun(map_id=map_id, category="음식점", requested_by=world.uid("u3"), status="done", created_at=at)
        db.add(run)
        db.flush()
        db.add(Candidate(run_id=run.id, place_id="secret_place_candidate", lat=37.5, lng=127.0, rank=1,
                         reason=f"{SECRET}_후보이유"))
        db.commit()


def _activity(world, map_id, at):
    """다른 카테고리에서 두 사람이 움직였다 — 카페 핀을 하나씩 찍는다(핀 생성도 행동이다, 6절)."""
    hours_ago = (world.now - at) / timedelta(hours=1)
    for who in ("u1", "u3"):
        world.pin(map_id, category="카페", by=who, hours_ago=hours_ago)


def test_accept_activity_followup_accept_then_declaration(world):
    map_id, food, cafes = _stall_world(world)
    t0 = world.now
    gateway = FakeGateway(good_stall)

    # 첫 제안(attempt 0) → 수락하면 지켜보기 시작
    assert _observe(world, map_id, gateway, t0) == "suggested"
    first = _active(world, map_id)
    assert first.attempt == 0
    _accept(world, first, t0 + timedelta(minutes=1))
    assert world.one(AgentSuggestion, id=first.id).followup == {"status": "watching",
                                                               "at": (t0 + timedelta(minutes=1)).isoformat()}
    state = _state(world, map_id, t0 + timedelta(minutes=2))
    assert [(t.status, t.text) for t in state.tracking] == [("watching", "음식점 · 추천 받기 뒤로 지켜보는 중")]

    # 추천을 받았지만(run) 아무도 지도에 올리지 않았다. 최소 대기 전에는 아무것도 하지 않는다
    _run(world, map_id, t0 + timedelta(minutes=3))
    assert _observe(world, map_id, gateway, t0 + timedelta(minutes=20)) in ("no_signal", "blocked")
    assert gateway.calls.count("diagnose") == 1

    # 다른 카테고리에서 두 사람이 움직였다 → 그대로 → 다음 방법(진단을 해 본 것과 함께)
    t1 = t0 + timedelta(minutes=50)
    _activity(world, map_id, t0 + timedelta(minutes=40))
    gateway = FakeGateway(next_method)
    assert _observe(world, map_id, gateway, t1) == "suggested"
    [inp] = gateway.inputs
    assert (inp["attempt"], inp["attempts"], inp["allowed_actions"]) == (
        1, [{"action": "open_recommend", "label": "음식점 추천 받기"}], ["search_place"])
    assert SECRET not in json.dumps(inp, ensure_ascii=False, default=str)
    second = _active(world, map_id)
    assert (second.attempt, second.followup_of) == (1, first.id)
    assert [a["type"] for a in second.actions] == ["search_place"]   # 이미 해 본 추천 받기는 검증이 뺐다
    assert world.one(AgentSuggestion, id=first.id).followup["status"] == "followed_up"
    run = world.rows(AgentRun, id=second.run_id)[0]
    assert [c["call_id"] for c in run.tool_calls][0] == "f1"
    assert run.tool_calls[0]["result"] == {"since_minutes": 49, "new_pins": 0}
    assert inp["followup_check"] == run.tool_calls[0]["result"]   # 모델 입력과 f1이 같은 값(#1347)
    assert run.priority["final_order"][0] == next(s["id"] for s in run.signals if s["features"].get("attempt") == 1)

    shown = _state(world, map_id, t1).active_suggestion
    assert (shown.attempt, [t.label for t in shown.tried]) == (1, ["음식점 추천 받기"])
    assert [(st.stage, st.text) for st in shown.steps][:2] == [
        ("감지", "음식점에 반대 의견 1개가 남은 뒤로 새 후보가 없어요"),
        ("후속 확인", "추천 받기 뒤로 49분 동안 음식점에 새 핀이 없었어요"),
    ]

    # 다음 방법도 수락 → 그대로 → 충돌 선언(코드 템플릿, 모델을 부르지 않는다)
    _accept(world, second, t1 + timedelta(minutes=1))
    t2 = t1 + timedelta(minutes=50)
    _activity(world, map_id, t1 + timedelta(minutes=40))
    gateway = FakeGateway(next_method)
    assert _observe(world, map_id, gateway, t2) == "suggested"
    assert "diagnose" not in gateway.calls
    third = _active(world, map_id)
    assert (third.attempt, third.followup_of, third.actions) == (2, second.id, [])
    assert third.followup["status"] == "declared"
    declared = _state(world, map_id, t2).active_suggestion
    assert [t.action_type for t in declared.tried] == ["open_recommend", "search_place"]
    texts = ["".join(seg.text for seg in line.segments) for line in declared.advice]
    assert texts[:2] == ["음식점 추천 받기를 해 봤어요", "음식점 검색을 해 봤어요"]
    assert texts[-1] == "어떤 조건을 지킬지는 여러분이 정해요"
    assert declared.actions == []
    run = world.rows(AgentRun, id=third.run_id)[0]
    assert run.used_model is False
    assert [st.stage for st in declared.steps][:2] == ["감지", "후속 확인"]

    # 충돌 선언 뒤로는 더 지켜보지 않는다
    _activity(world, map_id, t2 + timedelta(minutes=40))
    with world.factory() as db, session_scope(db) as s:
        flows.dismiss(s, row=s.get(AgentSuggestion, third.id), user_id=world.uid("u1"), now=t2 + timedelta(minutes=41))
    _observe(world, map_id, FakeGateway(next_method), t2 + timedelta(minutes=50))   # 다른 신호(반응 공백)는 날 수 있다
    assert max(r.attempt for r in world.rows(AgentSuggestion, map_id=map_id) if r.id != third.id) <= 1
    assert not [r for r in world.rows(AgentSuggestion, map_id=map_id) if r.followup_of == third.id]
    assert [(t.status, t.text) for t in _state(world, map_id, t2 + timedelta(minutes=51)).tracking] == [
        ("declared", "음식점 · 해 본 것을 남겼어요")]
    stored = json.dumps([r.followup for r in world.rows(AgentSuggestion, map_id=map_id)], ensure_ascii=False)
    assert SECRET not in stored and AGAINST_TEXT not in stored


def test_new_pin_resolves_the_episode(world):
    map_id, food, cafes = _stall_world(world)
    t0 = world.now
    assert _observe(world, map_id, FakeGateway(good_stall), t0) == "suggested"
    first = _active(world, map_id)
    _accept(world, first, t0 + timedelta(minutes=1))

    world.pin(map_id, hours_ago=-0.5)   # 수락 30분 뒤 음식점 새 핀
    _activity(world, map_id, t0 + timedelta(minutes=40))
    gateway = FakeGateway(next_method)
    _observe(world, map_id, gateway, t0 + timedelta(minutes=50))

    assert "diagnose" not in gateway.calls
    assert world.one(AgentSuggestion, id=first.id).followup["status"] == "resolved"
    assert world.one(AgentSuggestion, id=first.id).followup["reason"] == "new_pin"
    [line] = _state(world, map_id, t0 + timedelta(hours=1)).tracking
    assert (line.status, line.text) == ("resolved", "음식점 · 풀렸어요 — 새 핀이 올라왔어요")


def test_resolved_just_before_saving_is_stale(world, monkeypatch):
    """모델을 부르는 사이 새 핀이 올라오면 저장 직전 재확인(12.8)이 버리고 풀림을 쓴다."""
    map_id, food, cafes = _stall_world(world)
    t0 = world.now
    _observe(world, map_id, FakeGateway(good_stall), t0)
    first = _active(world, map_id)
    _accept(world, first, t0 + timedelta(minutes=1))
    _activity(world, map_id, t0 + timedelta(minutes=40))

    def pin_meanwhile(what):
        if what == "diagnose":
            world.pin(map_id, hours_ago=-0.7)

    assert _observe(world, map_id, FakeGateway(next_method, on_call=pin_meanwhile), t0 + timedelta(minutes=50)) == "stale"
    assert _active(world, map_id) is None
    assert world.one(AgentSuggestion, id=first.id).followup["status"] == "resolved"


def test_mode_off_stops_watching(world):
    map_id, food, cafes = _stall_world(world)
    t0 = world.now
    _observe(world, map_id, FakeGateway(good_stall), t0)
    first = _active(world, map_id)
    _accept(world, first, t0 + timedelta(minutes=1))
    with world.factory() as db, session_scope(db) as s:
        flows.change_settings(s, map_id=map_id, enabled=False, user_id=world.uid("u1"), now=t0 + timedelta(minutes=2))
    assert world.one(AgentSuggestion, id=first.id).followup is None
    assert _state(world, map_id, t0 + timedelta(minutes=3)).tracking == []


def test_dismissed_suggestion_is_not_watched(world):
    map_id, food, cafes = _stall_world(world)
    t0 = world.now
    _observe(world, map_id, FakeGateway(good_stall), t0)
    first = _active(world, map_id)
    with world.factory() as db, session_scope(db) as s:
        flows.dismiss(s, row=s.get(AgentSuggestion, first.id), user_id=world.uid("u1"), now=t0 + timedelta(minutes=1))
    _activity(world, map_id, t0 + timedelta(minutes=40))
    gateway = FakeGateway(next_method)
    _observe(world, map_id, gateway, t0 + timedelta(hours=4))
    assert world.one(AgentSuggestion, id=first.id).followup is None
    assert all(r.attempt == 0 for r in world.rows(AgentSuggestion, map_id=map_id))
    assert _state(world, map_id, t0 + timedelta(hours=4)).tracking == []

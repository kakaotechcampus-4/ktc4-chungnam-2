"""지도 현황 문단을 관찰 끝까지(명세 8.2, 12.4 9단계, #1168) — 실제 DB와 실제 다른 모듈 api로 본다.

- 관찰 끝에서 칸을 계산해 모델(Gateway.status)을 부르고, 검증을 통과한 문단만 agent_map_status에 덮어쓴다
- 칸이 같으면 다시 부르지 않는다(실패·검증 실패한 칸도). 칸이 바뀌면 다시 부른다
- 검증 다섯 가지 중 하나라도 걸리면 지난 문단을 그대로 둔다(outcome=invalid_claims). 처음이면 응답에 status가 없다(null)
- trigger=status 행은 used_model=true지만 지도 하루 상한(model_runs_today)에 세지 않는다
- 모델 호출 중 DB 연결을 들고 있지 않다(12.6). 문단과 칸에 사유 글, 이름, 장소 이름이 없다(2절 11, 13번)
- GET /maps/{mapId}/agent의 status가 api-spec(AgentMapStatus)과 같다
- 먼저 볼 곳(first_category)은 저장이 끝난 뒤의 카드를 본다 — 카드가 떠 있으면 비우고, 카드가 내려간 관찰에서는 다음 1순위,
  닫은 카드의 막힌 곳은 권하지 않는다(#1749)
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import text

from agent import deps, flows, service, tools
from agent.models import AgentMapStatus, AgentRun, AgentSuggestion
from agent.schemas import AgentCallFailed, AgentReply, AgentUsage, StatusOutput
from agent.tests.world import World, fake_places, real_now
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from llm import api as llm_api
from places import api as places_api

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))

SECRET = "비밀사유_주차가 전혀 안 돼요"
PLACE_NAME = "비밀장소_성수 칼국수"


def _spec_errors(name: str, body) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:pingo-spec#/components/schemas/{name}"}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)]


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({"pl_food": PLACE_NAME}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


@pytest.fixture()
def client(world):
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


class StatusGateway(deps.FixedAgentLlmGateway):
    """진단은 고정 응답 스텁(silent). 현황 문단은 reply가 있으면 그것을, 없으면 고정 응답 스텁을 낸다. 부를 때마다 칸을 남긴다."""

    def __init__(self, reply=None, on_call=None):
        self.reply = reply
        self.on_call = on_call or (lambda: None)
        self.cells: list[dict] = []

    def status(self, status_input):
        self.cells.append(dict(status_input))
        self.on_call()
        if self.reply is None:
            return super().status(status_input)
        out = self.reply(status_input) if callable(self.reply) else self.reply
        return AgentReply(out, AgentUsage(model="gpt-test", prompt_version="status-v1", tokens_in=120, tokens_out=40))


def observe(world, map_id, gateway, *, after=timedelta(0)):
    return flows.observe_map(map_id, world.now + after, session_factory=world.factory, gateway=gateway)


def status_runs(world, map_id) -> list[AgentRun]:
    return sorted(world.rows(AgentRun, map_id=map_id, trigger="status"), key=lambda r: r.started_at)


def _map(world):
    """음식점 핀 하나에 🚫(글) — 정체가 1순위. 카페, 관광지는 비었다."""
    map_id = world.map(start=world.today + timedelta(days=5))
    pin_id = world.pin(map_id, place_id="pl_food", hours_ago=100)
    world.react(pin_id, "u2", "against", hours_ago=20, text=SECRET)
    world.event(map_id)
    return map_id


def _output(cells, *, paragraph=None, **states):
    """칸에 맞는 출력(검증 통과) — states로 카테고리 상태를 바꾸고, paragraph로 문단을 바꾼다."""
    picks = {"음식점": "stalled", "카페": "empty", "관광지": "empty"} | states
    return StatusOutput.model_validate({
        "categories": [{"category": c["category"], "state": picks[c["category"]]} for c in cells["categories"]],
        "paragraph": paragraph or "음식점은 반대 의견이 나온 뒤로 새 후보가 없어요. 카페와 관광지는 아직 후보가 없어요. "
                                  "출발이 5일 남았으니 음식점부터 보면 좋겠어요.",
    })


# ---------------------------------------------------------------- 만들기, 응답

def test_observation_ends_with_a_status_paragraph(world, client):
    map_id = _map(world)
    gateway = StatusGateway(reply=lambda cells: _output(cells))

    observe(world, map_id, gateway)

    [cells] = gateway.cells
    assert cells["first_category"] == "음식점" and cells["dday"] == 5
    assert [c["category"] for c in cells["categories"]] == ["음식점", "카페", "관광지"]
    [run] = status_runs(world, map_id)
    assert (run.outcome, run.used_model, run.model, run.prompt_version, run.tokens_in) == (
        "status_updated", True, "gpt-test", "status-v1", 120)
    assert run.verification["failed"] == [] and run.outcome_detail["cells_hash"]
    row = world.one(AgentMapStatus, map_id=map_id)
    assert row.paragraph.endswith("음식점부터 보면 좋겠어요.") and row.run_id == run.id
    assert row.states == [{"category": "음식점", "state": "stalled"}, {"category": "카페", "state": "empty"},
                          {"category": "관광지", "state": "empty"}]
    # 새 이벤트는 없다 — 시트를 열 때 받는다
    assert not any(t.startswith("agent.status") for t, _ in world.agent_events(map_id))

    body = client("u1").get(f"/maps/{map_id}/agent").json()
    assert body["status"]["paragraph"] == row.paragraph
    assert _spec_errors("AgentState", body) == []


def test_fixed_stub_passes_verification(world):
    """dev 스텁(고정 응답)은 칸과 어긋나지 않는 상태와 숫자 없는 문구라 늘 통과한다 — dev에서도 저장·응답 경로를 지나간다."""
    map_id = _map(world)

    observe(world, map_id, deps.FixedAgentLlmGateway())

    [run] = status_runs(world, map_id)
    assert run.outcome == "status_updated" and run.used_model is True
    assert world.one(AgentMapStatus, map_id=map_id).paragraph == "지도 현황을 정리했어요. 음식점부터 보면 좋겠어요."


# ---------------------------------------------------------------- 칸이 바뀔 때만

def test_same_cells_do_not_call_again_and_changed_cells_do(world):
    map_id = _map(world)
    gateway = StatusGateway()

    observe(world, map_id, gateway)
    world.event(map_id, seconds_ago=1)
    observe(world, map_id, gateway, after=timedelta(minutes=5))   # 칸이 같다

    assert len(gateway.cells) == 1 and len(status_runs(world, map_id)) == 1

    world.pin(map_id, category="카페", hours_ago=0)                # 카페 후보가 생겼다 → 칸이 바뀐다
    world.event(map_id, seconds_ago=0)
    observe(world, map_id, gateway, after=timedelta(minutes=10))

    assert len(gateway.cells) == 2
    assert gateway.cells[1]["categories"][1]["pins"] == 1
    assert len(status_runs(world, map_id)) == 2


def test_failed_cells_are_not_asked_again(world):
    """모델이 실패한 칸으로는 다시 묻지 않는다(2절 10번) — 같은 칸이면 다음 관찰도 부르지 않는다."""
    map_id = _map(world)
    gateway = StatusGateway(reply=AgentCallFailed(reason="timeout", detail="LlmCallError(APITimeoutError)"))

    observe(world, map_id, gateway)
    observe(world, map_id, gateway, after=timedelta(minutes=5))

    [run] = status_runs(world, map_id)
    assert (run.outcome, run.used_model) == ("model_failed", True)
    assert run.outcome_detail["reason"] == "timeout" and run.verification is None
    assert len(gateway.cells) == 1
    assert world.rows(AgentMapStatus, map_id=map_id) == []


# ---------------------------------------------------------------- 먼저 볼 곳 — 카드가 말한다 (#1749)

def _tour_gap_map(world, *, start_in=30):
    """음식점·카페가 하나씩 확정돼 관광지만 비었다 — 관찰하면 관광지 공백 카드(코드 유형, 템플릿)가 뜬다."""
    map_id = world.map(start=world.today + timedelta(days=start_in))
    for category in ("음식점", "카페"):
        world.confirm(map_id, world.pin(map_id, category=category))
    world.event(map_id)
    return map_id


def _cafe_split(world, map_id):
    """카페 후보 하나에 셋이 ♥♥🚫 — 갈림 신호(weight 3)가 공백(2)보다 앞이다. 진단은 고정 응답 스텁이라 카드가 없다(silent)."""
    pin_id = world.pin(map_id, category="카페")
    for user, type_, ago in (("u1", "like", 30), ("u2", "like", 29), ("u3", "against", 28)):
        world.react(pin_id, user, type_, hours_ago=ago, text="웨이팅이 길어요" if type_ == "against" else None)
    world.event(map_id, seconds_ago=0)


def _card(world, map_id):
    return world.one(AgentSuggestion, map_id=map_id)


def test_active_card_empties_first_and_the_next_top_comes_after_it_goes(world):
    map_id = _tour_gap_map(world)
    gateway = StatusGateway()

    observe(world, map_id, gateway)                                 # 관광지 공백 카드가 뜬 관찰
    assert (_card(world, map_id).category, _card(world, map_id).status) == ("관광지", "active")
    assert gateway.cells[-1]["first_category"] is None

    _cafe_split(world, map_id)                                      # 카드가 떠 있는 채 더 급한 카페 갈림이 생겼다
    observe(world, map_id, gateway, after=timedelta(minutes=5))

    assert len(gateway.cells) == 2 and gateway.cells[-1]["categories"][1]["split_pins"] == 1
    assert (gateway.cells[-1]["first_category"], gateway.cells[-1]["first_reason"]) == (None, None)
    assert _card(world, map_id).status == "active"

    world.confirm(map_id, world.pin(map_id, category="관광지"), hours_ago=0)   # 관광지가 채워져 카드가 내려간다
    world.event(map_id, seconds_ago=0)
    observe(world, map_id, gateway, after=timedelta(minutes=10))

    assert _card(world, map_id).status == "superseded"
    assert (gateway.cells[-1]["first_category"], gateway.cells[-1]["first_reason"]) == ("카페", "의견이 갈린 핀이 있다")


def test_dismissed_card_is_not_recommended_next(world):
    """출발이 가까워 관광지 공백 카드가 카페 갈림보다 앞에 뜬다. 사람이 카드를 닫으면 다음 관찰의 문단은 닫은 관광지가 아니라 카페를
    권한다 — 닫은 막힌 곳은 정책이 duplicate로 막고 문단도 그 신호를 뺀다."""
    map_id = _tour_gap_map(world, start_in=2)
    _cafe_split(world, map_id)
    gateway = StatusGateway()

    observe(world, map_id, gateway)
    card = _card(world, map_id)
    assert (card.category, gateway.cells[-1]["first_category"]) == ("관광지", None)

    with world.factory() as db:
        assert service.resolve_suggestion(db, card.id, status="dismissed", user_id=world.uid("u1"),
                                          now=world.now + timedelta(minutes=1))
        db.commit()
    observe(world, map_id, gateway, after=timedelta(minutes=5))

    last = max(world.rows(AgentRun, map_id=map_id, trigger="activity"), key=lambda r: r.started_at)
    assert [b["reason"] for b in last.blocked] == ["duplicate"]   # 닫은 관광지 공백. 카페 갈림은 진단까지 갔다(silent)
    assert _card(world, map_id).status == "dismissed"             # 새 카드는 없다
    assert (gateway.cells[-1]["first_category"], gateway.cells[-1]["first_reason"]) == ("카페", "의견이 갈린 핀이 있다")


# ---------------------------------------------------------------- 검증 다섯 가지 — 걸리면 지난 문단 유지

BAD = {
    "categories": lambda cells: _output(cells).model_copy(update={"categories": _output(cells).categories[:2]}),
    "states": lambda cells: _output(cells, 음식점="decided"),
    "numbers": lambda cells: _output(cells, paragraph="음식점 후보가 3곳 있어요. 음식점부터 보면 좋겠어요."),
    "first_category": lambda cells: _output(cells, paragraph="카페부터 보면 좋겠어요. 음식점은 멈춰 있어요."),
    "forbidden": lambda cells: _output(cells, paragraph="음식점부터 보고 확정하세요."),
}


@pytest.mark.parametrize("check", list(BAD))
def test_each_check_keeps_the_previous_paragraph(world, client, check):
    map_id = _map(world)
    observe(world, map_id, StatusGateway(reply=lambda cells: _output(cells)))
    before = world.one(AgentMapStatus, map_id=map_id)

    world.pin(map_id, category="관광지", hours_ago=0)   # 칸을 바꿔 다시 부르게 한다
    world.event(map_id, seconds_ago=0)
    observe(world, map_id, StatusGateway(reply=BAD[check]), after=timedelta(minutes=5))

    first, second = status_runs(world, map_id)
    assert (first.outcome, second.outcome) == ("status_updated", "invalid_claims")
    assert check in second.verification["failed"]
    after = world.one(AgentMapStatus, map_id=map_id)
    assert (after.paragraph, after.cells_hash, after.run_id) == (before.paragraph, before.cells_hash, first.id)
    assert client("u1").get(f"/maps/{map_id}/agent").json()["status"]["paragraph"] == before.paragraph


def test_first_paragraph_invalid_shows_nothing(world, client):
    map_id = _map(world)

    observe(world, map_id, StatusGateway(reply=BAD["states"]))

    assert [r.outcome for r in status_runs(world, map_id)] == ["invalid_claims"]
    assert world.rows(AgentMapStatus, map_id=map_id) == []
    assert client("u1").get(f"/maps/{map_id}/agent").json()["status"] is None


# ---------------------------------------------------------------- 지도 하루 상한에 세지 않는다 (3절)

def test_status_call_is_not_counted_in_the_daily_cap(world):
    map_id = world.gap_map()   # 코드 유형만 — 진단(모델)을 부르지 않는 지도
    world.event(map_id)
    gateway = StatusGateway()

    observe(world, map_id, gateway)

    assert [r.used_model for r in status_runs(world, map_id)] == [True]
    with world.factory() as db:
        assert service.load_history(db, map_id, world.now).model_runs_today == 0
    assert "status" not in service.MODEL_RUN_TRIGGERS


def test_status_runs_do_not_block_diagnosis_even_past_the_cap(world, monkeypatch):
    """현황 행이 상한(구성원 3 × 4 = 12)보다 많아도 진단은 막히지 않는다."""
    map_id = _map(world)
    with world.factory() as db:
        for i in range(13):
            service.insert_run(db, map_id=map_id, started_at=world.now - timedelta(minutes=i + 1), trigger="status",
                               used_model=True, outcome="status_updated", outcome_detail={"cells_hash": f"h{i}"})
        db.commit()
    gateway = StatusGateway()

    assert observe(world, map_id, gateway) == "silent"   # 진단(고정 응답 스텁)을 불렀다 — model_cap이 아니다

    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.used_model is True and run.blocked == []


# ---------------------------------------------------------------- 세션, 원문

def test_no_db_connection_is_held_while_status_model_is_called(world, test_engine):
    map_id = _map(world)
    held = []
    gateway = StatusGateway(on_call=lambda: held.append(test_engine.pool.checkedout()))

    observe(world, map_id, gateway)

    assert held == [0]


def test_paragraph_and_cells_have_no_reason_text_or_names(world, factory):
    map_id = _map(world)

    observe(world, map_id, StatusGateway())

    with factory() as db:
        dumped = json.dumps(db.execute(text("SELECT row_to_json(t)::text FROM agent_map_status t")).scalars().all()
                            + db.execute(text("SELECT row_to_json(t)::text FROM agent_runs t WHERE trigger = 'status'"))
                            .scalars().all(), ensure_ascii=False)
    assert SECRET not in dumped and PLACE_NAME not in dumped and world.prefix not in dumped


def test_map_deleted_before_status_save_writes_nothing(world, monkeypatch):
    map_id = _map(world)
    gateway = StatusGateway(on_call=lambda: world.delete_map(map_id))

    observe(world, map_id, gateway)

    assert status_runs(world, map_id) == [] and world.rows(AgentMapStatus, map_id=map_id) == []


def test_purge_removes_the_status_row(world):
    map_id = _map(world)
    observe(world, map_id, StatusGateway())

    with world.factory() as db:
        from agent import api as agent_api
        assert agent_api.purge_map_data(db, map_ids=[map_id])["agent_map_status"] == 1
        db.commit()
    assert world.rows(AgentMapStatus, map_id=map_id) == []


def test_llm_status_usage_is_labelled(world, monkeypatch):
    """사용량 기록(#870) — 현황 문단 호출에는 agent_status 라벨이 붙는다(서버 호출이라 user_id 없음)."""
    map_id = _map(world)
    seen = []

    class Labelled(StatusGateway):
        def status(self, status_input):
            from llm import usage
            seen.append(usage.current_label())
            return super().status(status_input)

    observe(world, map_id, Labelled())

    [label] = seen
    assert (label.feature, label.map_id, label.user_id) == ("agent_status", map_id, None)
    assert "agent_status" in llm_api.__all__

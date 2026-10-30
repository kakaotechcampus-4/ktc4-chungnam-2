"""우리 조건 요약을 관찰 끝까지(명세 8절, 12.4 8단계, #586) — 실제 DB와 실제 pins·recommend api로 본다.

갱신 조건(새 사유 3개, 새 구성원의 첫 반응, 사라진 사유), 한 관찰에 카테고리 하나, 별도 agent_runs 행(trigger=summary,
used_model=false), agent.summary_updated 페이로드가 api-spec과 같은지, GET /maps/{mapId}/agent의 summaries, #422 분류
(🚫 글의 "고기 먹고 싶어요"는 must_keep이 아님), 삭제된 핀의 사유 포함, ② 실패, 그리고 2절 13번(어떤 agent 테이블에도
사유 글이 없다)과 11번(알러지 원문이 응답에 없다).

②는 이 파일의 대역(KeyedGateway)이다 — 글마다 정해 둔 키와 방향을 낸다(배지는 넣은 그대로, 진짜 ②와 같다). 진단은
고정 응답 스텁(silent)이다.
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import delete, text

from agent import core, deps, flows, tools
from agent.models import AgentCursor, AgentReasonSummary, AgentRun
from agent.tests.world import World, fake_places, real_now
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from llm import api as llm_api
from llm.service import PlanEvidenceFailed
from pins.models import Reaction
from places import api as places_api

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))

ALLERGY_TEXT = "비밀사유_새우 알러지가 있어서 못 먹어요"
TEXTS = {   # 글 → ②가 낼 (키, 방향) 줄. 없는 글은 키 없는 줄 하나(조건이 없는 글)
    "비밀사유_너무 매워요": [("spicy_focused", False)],
    "비밀사유_한식 말고 고기 먹고 싶어요": [("cuisine_korean", False), ("cuisine_bbq", True)],
    "비밀사유_고기 좋아요": [("cuisine_bbq", True)],
    "비밀사유_넓어서 좋아요": [("spacious", True)],
    "비밀사유_넓은 데는 휑해요": [("spacious", False)],
}
VAGUE_TEXT = "비밀사유_그냥 그래요"
ALL_TEXTS = [*TEXTS, ALLERGY_TEXT, VAGUE_TEXT]


def _spec_errors(name: str, body) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:pingo-spec#/components/schemas/{name}"}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)]


class KeyedGateway(deps.FixedAgentLlmGateway):
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.structured: list[str] = []

    def structure(self, raw):
        if self.fail:
            raise PlanEvidenceFailed("timeout")
        self.structured += [r["text"] for r in raw]
        return [
            [llm_api.EvidenceLine(source="reaction", text=r["text"], badge=r["badge"], fact_key=k, wants=w)
             for k, w in TEXTS.get(r["text"], ())]
            or [llm_api.EvidenceLine(source="reaction", text=r["text"], badge=r["badge"])]
            for r in raw
        ]


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
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


def observe(world, map_id, *, gateway=None, after=timedelta(0)):
    return flows.observe_map(map_id, world.now + after, session_factory=world.factory,
                             gateway=gateway or KeyedGateway())


def summary_runs(world, map_id) -> list[AgentRun]:
    return sorted(world.rows(AgentRun, map_id=map_id, trigger="summary"), key=lambda r: r.started_at)


def summary_events(world, map_id) -> list[dict]:
    return [p for t, p in world.agent_events(map_id) if t == "agent.summary_updated"]


def _five_section_map(world) -> tuple[str, dict[str, str]]:
    """음식점 핀 넷에 세 사람이 사유를 남긴 지도. 다섯 칸이 모두 찬다.

    u1: A 🚫 "너무 매워요" + 칩 「매워요」 · C ♥ "넓어서 좋아요" · D 🚫 칩 「비싸요」 「너무 멀어요」
    u2: A 🚫 칩 「매워요」 · B 🚫 "한식 말고 고기 먹고 싶어요" · C ♥ "그냥 그래요"
    u3: B ♥ "고기 좋아요" · C ♥ "넓은 데는 휑해요" · D 🚫 "새우 알러지가 있어서 못 먹어요"
    """
    map_id = world.map()
    a, b, c, d = (world.pin(map_id, hours_ago=100) for _ in range(4))
    ids = {
        "u1_a": world.react(a, "u1", "against", hours_ago=40, text="비밀사유_너무 매워요", chips=["food_spicy"]),
        "u1_c": world.react(c, "u1", "like", hours_ago=39, text="비밀사유_넓어서 좋아요"),
        "u1_d": world.react(d, "u1", "against", hours_ago=38, chips=["food_expensive", "common_far"]),
        "u2_a": world.react(a, "u2", "against", hours_ago=37, chips=["food_spicy"]),
        "u2_b": world.react(b, "u2", "against", hours_ago=36, text="비밀사유_한식 말고 고기 먹고 싶어요"),
        "u2_c": world.react(c, "u2", "like", hours_ago=35, text=VAGUE_TEXT),
        "u3_b": world.react(b, "u3", "like", hours_ago=34, text="비밀사유_고기 좋아요"),
        "u3_c": world.react(c, "u3", "like", hours_ago=33, text="비밀사유_넓은 데는 휑해요"),
        "u3_d": world.react(d, "u3", "against", hours_ago=32, text=ALLERGY_TEXT),
    }
    world.event(map_id)
    return map_id, ids


EXPECTED_FIVE = {
    "category": "음식점",
    "must_keep": [
        {"fact_key": "spicy_focused", "label": "매운맛 전문 제외", "member_count": 2},
        {"fact_key": "cuisine_korean", "label": "한식 제외", "member_count": 1},
    ],
    "common_prefs": [{"fact_key": "cuisine_bbq", "label": "고기구이 원함", "member_count": 2}],
    "split_prefs": [{"fact_key": "spacious", "label": "넓은 곳", "want_count": 1, "avoid_count": 1}],
    "vague_fixable": {"count": 2, "requests": [core.SUMMARY_REQUESTS["general"], core.SUMMARY_REQUESTS["far"]]},
    "not_filtered": {"count": 2, "notices": [core.SUMMARY_NOTICES["allergy"], core.SUMMARY_NOTICES["price"]]},
}


# ---------------------------------------------------------------- 다섯 칸, 저장, 이벤트, GET

def test_observation_summarizes_five_sections_and_announces(world, client):
    map_id, ids = _five_section_map(world)

    observe(world, map_id)

    [run] = summary_runs(world, map_id)
    assert (run.outcome, run.used_model, run.outcome_detail) == ("summarized", False, {"category": "음식점"})
    assert (run.model, run.prompt_version, run.tokens_in, run.tool_calls) == (None, None, 0, [])

    row = world.one(AgentReasonSummary, map_id=map_id)
    assert (row.category, row.based_on_reaction_count, row.run_id, row.updated_at) == (
        "음식점", 9, run.id, world.now)
    assert row.summary["reaction_ids"] == sorted(ids.values())
    assert row.summary["must_keep"][0] == {"fact_key": "spicy_focused", "wants": False, "member_count": 2,
                                           "reaction_ids": sorted([ids["u1_a"], ids["u2_a"]])}
    assert row.summary["not_filtered"] == {"count": 2, "reaction_ids": sorted([ids["u1_d"], ids["u3_d"]]),
                                           "notices": ["allergy", "price"]}

    [payload] = summary_events(world, map_id)
    assert _spec_errors("EvtAgentSummaryUpdated", {"id": 1, "event": "agent.summary_updated", "data": payload}) == []
    assert {k: v for k, v in payload.items() if k != "updated_at"} == EXPECTED_FIVE

    state = client("u2").get(f"/maps/{map_id}/agent")
    assert state.status_code == 200
    assert state.json()["summaries"] == [payload]
    assert all(t not in state.text for t in ALL_TEXTS)   # 알러지 원문을 포함해 사유 글이 응답에 없다


def test_summary_structuring_carries_server_usage_label(world):
    """요약의 ②는 사용량 기록(llm_calls, #870)에 agent_summary로 남는다. 서버 호출이라 user_id가 없다."""
    from llm import usage

    map_id, _ = _five_section_map(world)
    labels = []

    class Labelled(KeyedGateway):
        def structure(self, raw):
            labels.append(usage.current_label())
            return super().structure(raw)

    observe(world, map_id, gateway=Labelled())

    assert labels and all((l.feature, l.map_id, l.user_id) == ("agent_summary", map_id, None) for l in labels)


def test_no_agent_table_holds_reason_text_or_member(world):
    """요약을 거친 뒤 agent_* 어느 행에도 사유 글과 user_id가 없다(2절 13번, 11번)."""
    map_id, _ = _five_section_map(world)

    observe(world, map_id)

    assert world.rows(AgentReasonSummary, map_id=map_id)
    with world.factory() as db:
        for table in ("agent_runs", "agent_suggestions", "agent_cursors", "agent_suggestion_views",
                      "agent_reason_summaries", "agent_run_advice", "agent_settings"):
            dumped = json.dumps(db.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all(),
                                ensure_ascii=False)
            assert "비밀사유" not in dumped, table
    summary = json.dumps(world.one(AgentReasonSummary, map_id=map_id).summary, ensure_ascii=False)
    assert world.prefix not in summary   # 구성원 id(접두어가 붙은 user_id)도 없다


def test_deleted_pin_reasons_are_included(world):
    """추천처럼 삭제된 핀의 사유도 넣는다(8절, #243)."""
    map_id = world.map()
    gone = world.pin(map_id)
    world.react(gone, "u1", "against", hours_ago=10, chips=["food_spicy"])
    world.delete_pin(gone)
    world.event(map_id)

    observe(world, map_id)

    row = world.one(AgentReasonSummary, map_id=map_id)
    assert [(i["fact_key"], i["member_count"]) for i in row.summary["must_keep"]] == [("spicy_focused", 1)]


def test_summary_is_shown_while_mode_is_off(world, client):
    """요약은 모드와 상관없이 만들어진 카테고리만 싣는다(api-spec AgentState.summaries)."""
    map_id, _ = _five_section_map(world)
    observe(world, map_id)

    assert client("u1").put(f"/maps/{map_id}/agent/settings", json={"enabled": False}).status_code == 200
    body = client("u1").get(f"/maps/{map_id}/agent").json()

    assert (body["active_suggestion"], [s["category"] for s in body["summaries"]]) == (None, ["음식점"])


# ---------------------------------------------------------------- 갱신 조건 (8절)

def _one_reason_map(world, *, members=("u1", "u2", "u3")):
    map_id = world.map(members=members)
    pin = world.pin(map_id)
    world.react(pin, "u1", "against", hours_ago=30, chips=["food_spicy"])
    world.event(map_id)
    return map_id, pin


def test_two_new_reasons_wait_and_third_updates(world):
    map_id, pin = _one_reason_map(world)
    observe(world, map_id, after=-timedelta(hours=5))
    assert len(summary_runs(world, map_id)) == 1

    others = [world.pin(map_id) for _ in range(3)]
    world.react(others[0], "u1", "against", hours_ago=2, chips=["food_oily"])
    world.react(others[1], "u1", "against", hours_ago=2, chips=["food_wait"])
    observe(world, map_id, after=-timedelta(hours=1))
    assert len(summary_runs(world, map_id)) == 1   # 새 사유 2개 — 그대로

    world.react(others[2], "u1", "against", hours_ago=0.5, chips=["food_cramped"])
    observe(world, map_id)

    assert len(summary_runs(world, map_id)) == 2
    row = world.one(AgentReasonSummary, map_id=map_id)
    assert row.based_on_reaction_count == 4
    # 원함 칩 「웨이팅이 길어요」·「좁아요」는 preferred(#617)라 must_keep에 없고, u1 혼자라 common_prefs(2명 이상)에도 없다
    assert sorted(i["fact_key"] for i in row.summary["must_keep"]) == ["oily_focused", "spicy_focused"]
    assert row.summary["common_prefs"] == []
    assert len(summary_events(world, map_id)) == 2


def test_new_member_first_reaction_updates(world):
    """u4가 지난 요약 뒤에 이 지도에서 처음 반응했다 — 사유 없는 ♥여도 갱신한다. 이미 반응하던 u1의 새 반응은 아니다."""
    map_id, pin = _one_reason_map(world, members=("u1", "u2", "u3", "u4"))
    observe(world, map_id, after=-timedelta(hours=5))

    world.react(world.pin(map_id), "u1", "like", hours_ago=2)
    observe(world, map_id, after=-timedelta(hours=1))
    assert len(summary_runs(world, map_id)) == 1

    world.react(pin, "u4", "like", hours_ago=0.5)
    observe(world, map_id)

    assert len(summary_runs(world, map_id)) == 2
    assert world.one(AgentReasonSummary, map_id=map_id).updated_at == world.now


def test_removed_reason_updates_counts(world):
    """지난 요약이 본 반응이 지워지면(지도 나가기 #369, 반응 삭제) 다음 관찰에서 개수를 고친다."""
    map_id, pin = _one_reason_map(world)
    leaving = world.react(pin, "u2", "against", hours_ago=29, chips=["food_spicy"])
    observe(world, map_id, after=-timedelta(hours=5))
    assert world.one(AgentReasonSummary, map_id=map_id).summary["must_keep"][0]["member_count"] == 2

    with world.factory() as db:
        db.execute(delete(Reaction).where(Reaction.id == uuid.UUID(leaving)))
        db.commit()
    observe(world, map_id)

    row = world.one(AgentReasonSummary, map_id=map_id)
    assert (row.based_on_reaction_count, row.summary["must_keep"][0]["member_count"]) == (1, 1)


def test_one_category_per_observation_and_cursor_pulled_for_the_rest(world):
    map_id = world.map()
    world.react(world.pin(map_id, category="음식점"), "u1", "against", hours_ago=30, chips=["food_spicy"])
    world.react(world.pin(map_id, category="카페"), "u2", "against", hours_ago=30, chips=["cafe_noisy"])
    world.event(map_id)

    observe(world, map_id)

    assert [r.outcome_detail["category"] for r in summary_runs(world, map_id)] == ["음식점"]
    assert world.one(AgentCursor, map_id=map_id).next_check_at == world.now   # 남은 카페를 다음 tick에

    observe(world, map_id, after=timedelta(minutes=5))

    assert [r.outcome_detail["category"] for r in summary_runs(world, map_id)] == ["음식점", "카페"]
    cafe = world.one(AgentReasonSummary, map_id=map_id, category="카페")
    # 「시끄러워요」(quiet 원함)는 preferred(#617)라 must_keep에 없고, u2 혼자라 common_prefs(2명 이상)에도 없다
    assert len(cafe.summary["reaction_ids"]) == 1
    assert (cafe.summary["must_keep"], cafe.summary["common_prefs"]) == ([], [])
    assert len(summary_events(world, map_id)) == 2


def test_nothing_changed_writes_nothing(world):
    map_id, _ = _one_reason_map(world)
    observe(world, map_id)
    observe(world, map_id, after=timedelta(minutes=5))

    assert len(summary_runs(world, map_id)) == 1
    assert len(summary_events(world, map_id)) == 1


def test_structure_failure_keeps_old_summary_and_records_model_failed(world):
    """②가 실패하면 요약을 만들지 않고 이벤트도 없다. 재요청하지 않고 다음 관찰에서 다시 본다."""
    map_id, ids = _five_section_map(world)

    observe(world, map_id, gateway=KeyedGateway(fail=True))

    [run] = summary_runs(world, map_id)
    assert (run.outcome, run.used_model) == ("model_failed", False)
    assert run.outcome_detail == {"category": "음식점", "reason": "structure_failed", "detail": "PlanEvidenceFailed"}
    assert world.rows(AgentReasonSummary, map_id=map_id) == []
    assert summary_events(world, map_id) == []

    observe(world, map_id, after=timedelta(minutes=5))
    assert [r.outcome for r in summary_runs(world, map_id)] == ["model_failed", "summarized"]


def test_structured_texts_are_cached_across_observations(world):
    """같은 글은 (reaction_id, updated_at) 캐시로 한 번만 ②에 보낸다(8.1)."""
    map_id, _ = _one_reason_map(world)
    world.react(world.pin(map_id), "u2", "against", hours_ago=29, text="비밀사유_너무 매워요")
    gateway = KeyedGateway()
    observe(world, map_id, gateway=gateway, after=-timedelta(hours=5))
    for _ in range(3):
        world.react(world.pin(map_id), "u3", "like", hours_ago=1, text="비밀사유_고기 좋아요")

    observe(world, map_id, gateway=gateway)

    assert len(summary_runs(world, map_id)) == 2
    assert gateway.structured.count("비밀사유_너무 매워요") == 1
    assert gateway.structured.count("비밀사유_고기 좋아요") == 3

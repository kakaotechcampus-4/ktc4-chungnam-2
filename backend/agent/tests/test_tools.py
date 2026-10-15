"""모델 도구 8개(명세 10절, #533). 다른 모듈의 api.py만 감싸고, 별칭만 내보내고, 비공개 데이터가 없고, 기록에는 사유 글
대신 글자 수만 남는다.

도구는 자기 읽기 세션을 연다 — 실제로 커밋하는 픽스처(world.py)를 쓴다.
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from agent import core, snapshot, tools
from agent.tests.world import World, fake_places, real_now
from llm import api as llm_api
from llm import prompts as llm_prompts
from places import api as places_api
from places.schemas import FactLabel

LIKE_TEXT = "분위기가 아늑해서 좋아요"
AGAINST_TEXT = "주차할 곳이 없어요"


@pytest.fixture()
def factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture()
def world(factory):
    w = World(factory, real_now())
    yield w
    w.cleanup()


class Structurer:
    """② 대역 — 글마다 정해 둔 조건을 돌려주고 몇 번 불렸는지 센다."""

    def __init__(self, conditions=None, *, fail=False):
        self.conditions = conditions or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, raw):
        self.calls.append([r["text"] for r in raw])
        if self.fail:
            raise llm_api.PlanEvidenceFailed("call_failed")
        return [
            [llm_api.EvidenceLine(**(r | {"fact_key": k, "wants": w}))
             for k, w in self.conditions.get(r["text"], [(None, None)])]
            for r in raw
        ]


def _ctx(world, map_id, *, diagnosis="split", structure=None, cache=None):
    with world.factory() as db:
        snap = snapshot.build(db, map_id, world.now)
    return tools.ToolContext(
        map_id=map_id, snap=snap, allowed=tuple(tools.TOOLS) if diagnosis is None else llm_api.DIAGNOSIS_TOOLS[diagnosis],
        session_factory=world.factory, structure=structure or Structurer(), now=world.now,
        cache=cache or tools.StructureCache(),
    )


@pytest.fixture()
def split_map(world, monkeypatch):
    """음식점 핀 하나에 ♥ 둘(u1 글, u2 사유 없음), 🚫 하나(u3 글 + 칩 「좁아요」). 카페 핀 하나는 실시간 핀."""
    monkeypatch.setattr(places_api, "get_places", fake_places({"pl_food": "성수 칼국수"}))
    map_id = world.map()
    food = world.pin(map_id, place_id="pl_food", hours_ago=100)
    cafe = world.live_pin(map_id, "성수 카페", category="카페", by="u2", hours_ago=90)
    like = world.react(food, "u1", "like", hours_ago=30, text=LIKE_TEXT)
    world.react(food, "u2", "like", hours_ago=25)
    against = world.react(food, "u3", "against", hours_ago=20, text=AGAINST_TEXT, chips=["food_cramped"])
    return {"map_id": map_id, "food": food, "cafe": cafe, "like": like, "against": against}


# ---------------------------------------------------------------- 허용 목록, 오류

def test_tools_cover_llm_specs_and_agent_keeps_no_copy_of_the_allowed_list():
    # 유형별 허용 목록은 llm.api.DIAGNOSIS_TOOLS 한 곳이다(#564) — agent에 사본이 없다
    assert not hasattr(tools, "ALLOWED_TOOLS")
    assert set(tools.TOOLS) == set(llm_prompts.AGENT_TOOL_SPECS) | {"get_activity"}
    assert all(name in tools.TOOLS for names in llm_api.DIAGNOSIS_TOOLS.values() for name in names)


def test_tool_outside_diagnosis_list_is_not_found(world, split_map):
    ctx = _ctx(world, split_map["map_id"], diagnosis="stall")

    assert ctx.run("t1", "compare_reasons", {"pin_id": split_map["food"], "category": None}) == {"error": "NOT_FOUND"}
    assert ctx.run("t2", "no_such_tool", {}) == {"error": "NOT_FOUND"}
    assert [c["call_id"] for c in ctx.calls] == ["t1", "t2"]


# ---------------------------------------------------------------- 도구별 반환

def test_get_map_overview(world, split_map):
    ctx = _ctx(world, split_map["map_id"], diagnosis="stall")

    result = ctx.run("t1", "get_map_overview", {})

    assert result["dday"] == 30 and result["member_count"] == 3
    assert result["categories"] == [
        {"category": "음식점", "pins": 1, "confirmed": 0}, {"category": "카페", "pins": 1, "confirmed": 0},
        {"category": "관광지", "pins": 0, "confirmed": 0},
    ]
    assert result["last_activity_at"] == (world.now - timedelta(hours=20)).isoformat()


def test_get_activity_counts_since(world, split_map):
    ctx = _ctx(world, split_map["map_id"], diagnosis=None)

    result = ctx.run("t1", "get_activity", {"since": (world.now - timedelta(hours=26)).isoformat()})

    assert result["counts"] == {"pin": 0, "reaction": 2, "shortlist": 0}
    assert (result["distinct_actors"], result["median_gap_minutes"]) == (2, 300.0)
    assert ctx.run("t2", "get_activity", {"since": "어제"}) == {"error": "NOT_FOUND"}


def test_get_reaction_matrix_uses_aliases_and_names(world, split_map):
    ctx = _ctx(world, split_map["map_id"])

    result = ctx.run("t1", "get_reaction_matrix", {"category": "음식점"})

    assert result == {
        "category": "음식점", "members": ["m1", "m2", "m3"], "total": 1,
        "pins": [{"pin_id": split_map["food"], "name": "성수 칼국수",
                  "reactions": {"m1": "like", "m2": "like", "m3": "against"}}],
    }
    cafe = ctx.run("t2", "get_reaction_matrix", {"category": "카페"})
    assert cafe["pins"][0]["name"] == "성수 카페" and cafe["pins"][0]["reactions"] == {"m1": None, "m2": None, "m3": None}
    assert ctx.run("t3", "get_reaction_matrix", {"category": "숙소"}) == {"error": "NOT_FOUND"}


def test_get_reasons_filters_and_returns_text_to_model_but_not_to_log(world, split_map):
    ctx = _ctx(world, split_map["map_id"])

    result = ctx.run("t1", "get_reasons", {"pin_ids": [split_map["food"]], "category": None, "types": ["against"]})

    [reason] = result["reasons"]
    assert result["total"] == 1
    assert reason["reaction_id"] == split_map["against"] and reason["text"] == AGAINST_TEXT
    assert reason["member_alias"] == "m3" and reason["type"] == "against"
    assert reason["chips"] == [{"chip_id": "food_cramped", "label": "좁아요", "fact_key": "spacious", "wants": True}]
    [logged] = ctx.calls[0]["result"]["reasons"]
    assert logged["text_len"] == len(AGAINST_TEXT) and "text" not in logged
    assert AGAINST_TEXT not in json.dumps(ctx.calls, ensure_ascii=False)
    assert ctx.results["t1"] is result   # 검증용 원래 결과는 메모리에만


def test_get_reasons_by_category_newest_first(world, split_map):
    ctx = _ctx(world, split_map["map_id"])

    result = ctx.run("t1", "get_reasons", {"pin_ids": None, "category": "음식점", "types": None})

    assert [r["reaction_id"] for r in result["reasons"]] == [split_map["against"], split_map["like"]]


def test_structure_reasons_uses_planner_for_text_and_chip_table_for_chips(world, split_map):
    structure = Structurer({AGAINST_TEXT: [("parking_available", True)], LIKE_TEXT: [(None, None)]})
    ctx = _ctx(world, split_map["map_id"], structure=structure)
    args = {"reaction_ids": [split_map["against"], split_map["like"], "no-such-id"]}

    result = ctx.run("t1", "structure_reasons", args)

    assert result["total"] == 2 and result["not_found"] == ["no-such-id"]
    assert result["reasons"] == [
        {"reaction_id": split_map["against"], "type": "against", "lines": [
            {"fact_key": "parking_available", "wants": True, "badge": "required"},   # 글 → ②
            {"fact_key": "spacious", "wants": True, "badge": "required"},            # 칩 → 칩 표 그대로
        ]},
        {"reaction_id": split_map["like"], "type": "like", "lines": [
            {"fact_key": None, "wants": None, "badge": "preferred"}]},
    ]
    assert structure.calls == [[AGAINST_TEXT, LIKE_TEXT]]   # 한 번에 모아서


def test_structure_reasons_demotes_wanted_cuisine_in_against_text(world):
    """#422(recommend와 같은 규칙, #564): 🚫 글의 음식 종류 "원함"은 preferred로 내려간다. 피함과 다른 키는 그대로다."""
    map_id = world.map()
    pin_id = world.pin(map_id, hours_ago=100)
    against = world.react(pin_id, "u2", "against", hours_ago=20, text="고기 먹고 싶어요, 매운 건 싫어요")
    structure = Structurer({"고기 먹고 싶어요, 매운 건 싫어요": [
        ("cuisine_bbq", True), ("cuisine_korean", False), ("parking_available", True),
    ]})
    ctx = _ctx(world, map_id, structure=structure)

    [reason] = ctx.run("t1", "structure_reasons", {"reaction_ids": [against]})["reasons"]

    assert reason["lines"] == [
        {"fact_key": "cuisine_bbq", "wants": True, "badge": "preferred"},       # 가게의 정체 원함 → 선호
        {"fact_key": "cuisine_korean", "wants": False, "badge": "required"},    # 피함은 그대로
        {"fact_key": "parking_available", "wants": True, "badge": "required"},  # 정체가 아닌 키는 그대로
    ]


def test_structure_cache_by_reaction_and_updated_at(world, split_map):
    structure, cache = Structurer(), tools.StructureCache()
    args = {"reaction_ids": [split_map["against"]]}

    _ctx(world, split_map["map_id"], structure=structure, cache=cache).run("t1", "structure_reasons", args)
    _ctx(world, split_map["map_id"], structure=structure, cache=cache).run("t1", "structure_reasons", args)
    assert structure.calls == [[AGAINST_TEXT]]   # 두 번째는 캐시

    world.touch_reaction(split_map["against"], hours_ago=1, text="너무 시끄러워요")
    _ctx(world, split_map["map_id"], structure=structure, cache=cache).run("t1", "structure_reasons", args)
    assert structure.calls[-1] == ["너무 시끄러워요"]   # 글을 고치면 updated_at이 바뀌어 다시 부른다


def test_structure_failure_is_unavailable(world, split_map):
    ctx = _ctx(world, split_map["map_id"], structure=Structurer(fail=True))

    assert ctx.run("t1", "structure_reasons", {"reaction_ids": [split_map["against"]]}) == {"error": "UNAVAILABLE"}
    assert ctx.run("t2", "compare_reasons", {"pin_id": split_map["food"], "category": None}) == {"error": "UNAVAILABLE"}


def test_compare_reasons_by_pin(world, split_map):
    structure = Structurer({AGAINST_TEXT: [("parking_available", True)], LIKE_TEXT: [("spacious", False)]})
    ctx = _ctx(world, split_map["map_id"], structure=structure)

    result = ctx.run("t1", "compare_reasons", {"pin_id": split_map["food"], "category": None})

    assert result["conflict_type"] == "same_axis"   # ♥ 넓은 곳 원하지 않음 / 🚫 칩 「좁아요」(넓은 곳 원함)
    assert result["keys"] == [
        {"fact_key": "parking_available", "want": [{"reaction_id": split_map["against"], "side": "against"}],
         "avoid": []},
        {"fact_key": "spacious", "want": [{"reaction_id": split_map["against"], "side": "against"}],
         "avoid": [{"reaction_id": split_map["like"], "side": "like"}]},
    ]
    assert ctx.run("t2", "compare_reasons", {"pin_id": None, "category": "음식점"})["conflict_type"] == "same_axis"
    assert ctx.run("t3", "compare_reasons", {"pin_id": None, "category": None}) == {"error": "NOT_FOUND"}


def test_get_place_facts_only_for_pins_on_map_and_unknown_stays_unknown(world, split_map, monkeypatch):
    def get_facts(place_ids, *, db=None):
        return {pid: [FactLabel("quiet", True, "known"), FactLabel("spacious", None, "unknown")] for pid in place_ids}

    monkeypatch.setattr(places_api, "get_facts", get_facts)
    ctx = _ctx(world, split_map["map_id"])

    result = ctx.run("t1", "get_place_facts", {"place_ids": ["pl_food", "pl_elsewhere"],
                                               "fact_keys": ["quiet", "spacious", "parking_available"]})

    assert result["facts"] == [
        {"place_id": "pl_food", "fact_key": "quiet", "value": True, "confidence": "known"},
        {"place_id": "pl_food", "fact_key": "spacious", "value": None, "confidence": "unknown"},
        {"place_id": "pl_food", "fact_key": "parking_available", "value": None, "confidence": "unknown"},
    ]
    assert result["not_found"] == ["pl_elsewhere"] and result["total"] == 3


def test_get_readiness(world, split_map):
    ctx = _ctx(world, split_map["map_id"], diagnosis="stall")

    result = ctx.run("t1", "get_readiness", {"category": "음식점"})

    assert result["category"] == "음식점" and result["ready"] is True
    assert {"answered_count", "required_count"} <= set(result)
    assert ctx.run("t2", "get_readiness", {"category": "숙소"}) == {"error": "NOT_FOUND"}


def test_results_are_capped_with_total(world, monkeypatch):
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    map_id = world.map()
    for _ in range(32):
        world.pin(map_id)
    ctx = _ctx(world, map_id)

    result = ctx.run("t1", "get_reaction_matrix", {"category": "음식점"})

    assert (len(result["pins"]), result["total"]) == (30, 32)


# ---------------------------------------------------------------- 비공개 데이터와 user_id (17절 1번, 2절 2번, 11번)

def test_tool_results_have_no_private_data_or_user_ids(world, split_map, monkeypatch):
    monkeypatch.setattr(places_api, "get_facts", lambda ids, *, db=None: {})
    secrets = world.private_run(split_map["map_id"], secret="비밀사유런")
    ctx = _ctx(world, split_map["map_id"], diagnosis=None)
    food = split_map["food"]
    calls = [
        ("get_map_overview", {}), ("get_activity", {"since": None}), ("get_reaction_matrix", {"category": "카페"}),
        ("get_reaction_matrix", {"category": "음식점"}), ("get_reasons", {"pin_ids": None, "category": None, "types": None}),
        ("structure_reasons", {"reaction_ids": [split_map["like"], split_map["against"]]}),
        ("compare_reasons", {"pin_id": None, "category": "카페"}), ("compare_reasons", {"pin_id": food, "category": None}),
        ("get_place_facts", {"place_ids": ["pl_food", "secret_place_candidate"], "fact_keys": None}),
        ("get_readiness", {"category": "카페"}), ("get_readiness", {"category": "음식점"}),
    ]

    results = [ctx.run(f"t{i}", name, args) for i, (name, args) in enumerate(calls, start=1)]

    dumped = json.dumps([results, ctx.calls], ensure_ascii=False, default=str)
    for leaked in secrets:
        if leaked != "secret_place_candidate":   # 모델이 인자로 넣은 id는 not_found로 되돌아온다
            assert leaked not in dumped, leaked
    assert "secret_place_candidate" not in json.dumps(results[8]["facts"])
    for user in ("u1", "u2", "u3"):
        assert world.uid(user) not in dumped

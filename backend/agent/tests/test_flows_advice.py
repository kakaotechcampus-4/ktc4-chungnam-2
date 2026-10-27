"""추천 막힘 조언을 끝까지(명세 9절, 17절 2·12·13, #587, #750) — 실제 DB, 실제 recommend.api(run 조회와 시뮬레이션), 코드
절차(core.choose_run_advice)를 지나간다. 모델은 없다.

run은 recommend 모듈 테스트(test_run_reads_api.py)와 같은 판이다: 카페 반경 1000m, 근거 줄 셋(다른 구성원의 「붐빔」, 요청자
본인의 「넓은 곳」, 요청자 본인의 조건 없는 글). 장소는 판마다 고른다 — 기본 판은 단계마다 한 곳씩만 빠져 뚜렷한 탈락이 없고,
SOFT는 실격 조건, RADIUS는 반경, EXHAUSTED는 이미 제안한 곳이 뚜렷하게(ADVICE_CLEAR_DROP 이상) 많다. 결과는 ok 한 곳이라
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

from agent import core, deps, flows, service
from agent.models import AgentRun, AgentRunAdvice
from agent.tests.world import World, real_now
from auth.testing import ensure_users, session_cookie
from common.database import get_db_session, session_scope
from common.errors import AppError
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


def _at(place_id, lat=35.0005, lng=129.0005):
    return PlaceStub(place_id=place_id, lat=lat, lng=lng)


def _many(prefix, n, **kw):
    return [_at(f"{prefix}{i}", **kw) for i in range(n)]


# 장소 id의 앞 글자로 라벨이 정해진다: crowded는 붐빔(다른 구성원 줄이 거른다), narrow는 좁음(본인 줄이 거른다)
BASE = [_at("ok"), _at("crowded"), _at("narrow"), _at("far", lat=35.0135, lng=129.0), _at("proposed")]   # far는 약 1500m
SOFT = [_at("ok"), *_many("crowded", 6), *_many("narrow", 5)]
RADIUS = [_at("ok"), *_many("near", 5, lat=35.0108, lng=129.0)]   # 약 1200m — 버튼 한 번(× 20/15 = 1333m)이면 들어온다
EXHAUSTED = [_at("ok"), *_many("proposed", 6)]
MORE = [_at("ok2"), _at("ok3")]


def _facts(place_id):
    return {"is_crowded_large": place_id.startswith("crowded"), "spacious": not place_id.startswith("narrow")}


class FakePlaceSearch:
    def __init__(self, places):
        self.places = places

    def search_nearby(self, *, category, circles):
        return self.places

    def get_places(self, place_ids):
        return {}

    def count_curated(self, *, category, circles):
        return len(self.places)


class FakePlaceFacts:
    def get_facts(self, place_ids):
        return {pid: [FactLabel(k, v, "known") for k, v in _facts(pid).items()] for pid in place_ids}


@pytest.fixture()
def places(monkeypatch):
    search = FakePlaceSearch(list(BASE))
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


def said(advice) -> list[str]:
    """조언 문장들. 숫자와 줄 이름은 claim 슬롯이라 줄마다 text 조각 하나다(#717)."""
    assert all([s.kind for s in line.segments] == ["text"] for line in advice.advice)
    return [line.segments[0].text for line in advice.advice]


def make_run(world, map_id, *, execute=True, walk=15, requester="u1", vague=True) -> str:
    """조언 대상 판. execute=False면 근거 수집 중인 run이다. 이미 제안한 곳은 proposed로 시작하는 장소 전부다."""
    with world.factory() as db:
        run = RecommendRun(map_id=map_id, category="카페", requested_by=world.uid(requester),
                           status="collecting_evidence", default_radius_walk_min=walk)
        db.add(run)
        db.flush()
        db.add(Region(run_id=run.id, signature="sig", label="기본 반경", center_lat=35.0, center_lng=129.0,
                      radius_m=1000, anchor_points=[[35.0, 129.0]], confirmed=True))
        line = {"source": "reaction", "badge": "required"}
        lines = [
            line | {"author_id": world.uid("u2"), "text": OTHER_TEXT, "fact_key": "is_crowded_large", "wants": None},
            line | {"author_id": world.uid(requester), "text": OWN_TEXT, "fact_key": "spacious", "wants": True},
        ]
        if vague:
            lines.append(line | {"author_id": world.uid(requester), "text": VAGUE_TEXT})
        recommend_service.add_reaction_evidence(db, run_id=run.id, lines=lines)
        search = recommend_deps.get_place_search_gateway()
        proposed = [p.place_id for p in search.places if p.place_id.startswith("proposed")]
        recommend_service.add_exclusions(db, map_id=map_id, category="카페", place_ids=proposed, reason="proposed",
                                         run_id=run.id, requested_by=world.uid(requester))
        if execute:
            recommend_flows.execute_run(db, run_id=str(run.id), place_search=search,
                                        place_facts=recommend_deps.get_place_facts_gateway())
        db.commit()
        return str(run.id)


def advise(world, run_id, requester="u1"):
    return flows.advise_run(run_id, world.uid(requester), session_factory=world.factory)


def advice_rows(world, run_id):
    return world.rows(AgentRunAdvice, run_id=uuid.UUID(run_id))


def advice_runs(world, map_id):
    return world.rows(AgentRun, map_id=map_id, trigger="run_advice")


def evidence(world, run_id):
    with world.factory() as db:
        return recommend_api.get_run_evidence(db, run_id=run_id)


def line_id(world, run_id, text):
    return next(line["line_id"] for line in evidence(world, run_id) if line["text"] == text)


def _dump(rows, *cols) -> str:
    return json.dumps([{c: getattr(r, c) for c in cols} for r in rows], ensure_ascii=False, default=str)


def _forbid(*args, **kwargs):
    raise AssertionError("다시 계산하면 안 된다")


# ---------------------------------------------------------------- 종류별 (17절 2)

def test_soft_relax_button_only_for_own_line_and_nothing_private_is_said_or_stored(world, map_id, places):
    places.places = SOFT
    run_id = make_run(world, map_id)
    labels = recommend_api.fact_labels()

    advice = advise(world, run_id)

    assert advice.kind == "soft_relax"
    assert said(advice) == [   # 다른 구성원 줄(6곳)이 더 많이 걸렀어도 본인 줄(5곳)을 말하고 버튼은 본인 줄에만
        f"「{labels['is_crowded_large']}」 조건을 빼면 6곳이 더 남아요.",
        f"「{labels['spacious']} 원함」 조건을 빼면 5곳이 더 남아요.",
    ]
    assert [a.model_dump(mode="json") for a in advice.actions] == [{
        "index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
        "params": {"run_id": run_id, "evidence_line_ids": [line_id(world, run_id, OWN_TEXT)]},
    }]
    body = advice.model_dump_json()
    stored = _dump(advice_rows(world, run_id), "kind", "claims", "advice", "actions")
    logged = _dump(advice_runs(world, map_id), "tool_calls", "verification", "outcome_detail")
    for secret in (*SECRETS, world.uid("u1"), world.uid("u2")):
        assert secret not in body
        assert secret not in stored
        assert secret not in logged   # 읽은 근거 줄 기록에도 글과 쓴 사람이 없다(2절 13번)


def test_radius_says_what_one_press_of_the_button_gives(world, map_id, places):
    places.places = RADIUS
    run_id = make_run(world, map_id)

    advice = advise(world, run_id)

    assert said(advice) == ["반경 넓히기를 한 번 누르면 5곳이 더 남아요."]
    assert [a.model_dump(mode="json") for a in advice.actions] == [
        {"index": 0, "type": "widen_radius", "label": "반경 넓히기", "params": {"run_id": run_id}},
    ]
    [row] = advice_runs(world, map_id)
    [sim] = [c for c in row.tool_calls if c["name"] == "simulate_filter"]
    assert sim["args"] == {"radius_factor": 20 / 15, "disable_line_ids": []}   # 버튼 한 번의 배율 하나만


def test_no_widen_when_the_run_is_already_at_the_limit(world, map_id, places):
    places.places = RADIUS
    run_id = make_run(world, map_id, walk=30, vague=False)

    assert advise(world, run_id) is None
    assert advice_rows(world, run_id)[0].kind is None
    assert [c["name"] for c in advice_runs(world, map_id)[0].tool_calls] == ["get_run_funnel", "get_run_evidence"]


def test_exhausted(world, map_id, places):
    places.places = EXHAUSTED
    run_id = make_run(world, map_id)

    advice = advise(world, run_id)

    assert (advice.kind, said(advice), advice.actions) == (
        "exhausted", ["이미 보여 줬거나 거절한 6곳은 다시 추천하지 않아요."], [])


def test_vague_reason_on_a_board_without_clear_drops(world, map_id):
    run_id = make_run(world, map_id)

    advice = advise(world, run_id)

    assert advice.kind == "vague_reason"
    assert said(advice) == ["조건으로 읽지 못한 글이 있어 추천에 반영되지 않았어요.",
                            "'조용한 곳이 좋아요'처럼 원하는 점을 적으면 반영돼요."]
    assert advice.actions[0].params.evidence_line_ids == [line_id(world, run_id, VAGUE_TEXT)]


# ---------------------------------------------------------------- 기록

def test_advice_is_logged_as_run_advice_without_the_model(world, map_id, places):
    places.places = SOFT
    run_id = make_run(world, map_id)

    advise(world, run_id)

    [row] = advice_runs(world, map_id)
    assert (row.trigger, row.outcome, row.used_model) == ("run_advice", "advised", False)
    assert (row.model, row.prompt_version, row.tokens_in, row.tokens_out) == (None, None, 0, 0)
    assert row.outcome_detail == {"run_id": run_id, "stored": True, "decision": "advise", "kind": "soft_relax"}
    # 깔때기(t0), 근거 줄(t1), 조건 줄 둘을 하나씩 끈 시뮬레이션. 반경 밖은 뚜렷하지 않아 넓혀 보지 않는다
    assert [(c["call_id"], c["name"]) for c in row.tool_calls] == [
        ("t0", "get_run_funnel"), ("t1", "get_run_evidence"), ("t2", "simulate_filter"), ("t3", "simulate_filter")]
    claimed = {c["call_id"] for c in advice_rows(world, run_id)[0].claims}
    assert claimed <= {c["call_id"] for c in row.tool_calls}   # claim은 기록된 읽기를 가리킨다
    assert advice_rows(world, run_id)[0].agent_run_id == row.id
    with world.factory() as db:
        assert service.load_history(db, map_id, world.now).model_runs_today == 0   # 9절: 지도 상한에 세지 않는다


# ---------------------------------------------------------------- run당 1회 (17절 13)

def test_second_request_returns_the_stored_advice_without_recomputing(world, map_id, monkeypatch):
    run_id = make_run(world, map_id)
    first = advise(world, run_id)
    monkeypatch.setattr(core, "choose_run_advice", _forbid)
    monkeypatch.setattr(recommend_api, "simulate_filter", _forbid)

    second = advise(world, run_id)

    assert second == first
    assert len(advice_runs(world, map_id)) == 1


def test_concurrent_requests_store_one_advice_and_return_the_same(world, map_id, monkeypatch):
    run_id = make_run(world, map_id)
    both_in = threading.Barrier(2, timeout=10)   # 두 요청이 모두 "저장된 것 없음"을 본 뒤 고르기에 들어간다
    choose = core.choose_run_advice

    def waiting(*args, **kwargs):
        both_in.wait()
        return choose(*args, **kwargs)

    monkeypatch.setattr(core, "choose_run_advice", waiting)
    results, errors = [], []

    def call():
        try:
            results.append(advise(world, run_id))
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


# ---------------------------------------------------------------- 대상 아님, 침묵

def test_not_a_target_writes_nothing(world, map_id, places):
    places.places = BASE + MORE   # 결과 3곳, 같은 카테고리 run 1개
    run_id = make_run(world, map_id)

    assert advise(world, run_id) is None
    assert advice_rows(world, run_id) == [] and advice_runs(world, map_id) == []


def test_three_runs_in_the_same_category_make_a_target(world, map_id, places):
    places.places = BASE + MORE
    runs = [make_run(world, map_id) for _ in range(3)]

    assert advise(world, runs[1]) is None   # 두 번째 run까지는 2개 — 나중 run은 세지 않는다
    assert advice_rows(world, runs[1]) == []
    assert advise(world, runs[2]) is not None


def test_unfinished_run_is_not_a_target(world, map_id):
    run_id = make_run(world, map_id, execute=False)

    assert advise(world, run_id) is None
    assert advice_rows(world, run_id) == []


def test_silence_is_stored_empty_and_never_computed_again(world, map_id, monkeypatch):
    run_id = make_run(world, map_id, vague=False)   # 뚜렷한 탈락도, 읽지 못한 글도 없다

    assert advise(world, run_id) is None
    [row] = advice_rows(world, run_id)
    assert (row.kind, row.claims, row.advice, row.actions) == (None, [], [], [])
    assert advice_runs(world, map_id)[0].outcome_detail["decision"] == "silent"
    assert advice_runs(world, map_id)[0].outcome == "silent"
    monkeypatch.setattr(core, "choose_run_advice", _forbid)
    assert advise(world, run_id) is None


# ---------------------------------------------------------------- 계산 중 예외 (#750 — 조언 없음과 가른다)

def _boom(*args, **kwargs):
    raise RuntimeError(f"예외 메시지 {OWN_TEXT}")


@pytest.mark.parametrize("target", ["funnel", "simulate", "choose"])
def test_exception_is_raised_and_logged_and_the_next_request_tries_again(world, map_id, places, monkeypatch, target):
    """읽기, 시뮬레이션, 고르기가 예외를 내면 조언 없음(None)으로 삼키지 않고 올린다. error 행만 남기고 조언은 저장하지 않아
    다음 요청이 다시 만든다. outcome_detail은 run과 예외 클래스 이름뿐이다 — 예외 메시지는 남기지 않는다."""
    places.places = SOFT
    run_id = make_run(world, map_id)
    where = {"funnel": (recommend_api, "get_run_funnel"), "simulate": (recommend_api, "simulate_filter"),
             "choose": (core, "choose_run_advice")}[target]
    with monkeypatch.context() as m:
        m.setattr(*where, _boom)
        with pytest.raises(RuntimeError):
            advise(world, run_id)

    assert advice_rows(world, run_id) == []
    [row] = advice_runs(world, map_id)
    assert (row.outcome, row.used_model) == ("error", False)
    assert row.outcome_detail == {"run_id": run_id, "error": "RuntimeError"}
    assert "예외 메시지" not in _dump([row], "tool_calls", "outcome_detail")

    again = advise(world, run_id)
    assert again is not None and again.kind == "soft_relax"
    assert sorted(r.outcome for r in advice_runs(world, map_id)) == ["advised", "error"]


def test_only_the_requester_and_only_existing_runs(world, map_id):
    run_id = make_run(world, map_id)

    with pytest.raises(AppError) as forbidden:
        advise(world, run_id, requester="u2")
    with pytest.raises(AppError) as missing:
        advise(world, str(uuid.uuid4()))

    assert (forbidden.value.code, missing.value.code) == ("FORBIDDEN", "NOT_FOUND")


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
        c = TestClient(app, cookies=session_cookie(world.uid(name)), raise_server_exceptions=False)
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


def test_router_permissions_and_204(world, map_id, client, places):
    with world.factory() as db:
        ensure_users(db, world.uid("outsider"))
        db.commit()
    world.user_ids.add(world.uid("outsider"))
    places.places = BASE + MORE
    not_target = make_run(world, map_id)

    assert client("outsider").get(f"/runs/{not_target}/advice").status_code == 404   # 비구성원은 존재를 모른다
    assert client("u2").get(f"/runs/{not_target}/advice").status_code == 403         # 구성원이지만 요청자가 아니다
    assert client("u1").get(f"/runs/{uuid.uuid4()}/advice").status_code == 404
    empty = client("u1").get(f"/runs/{not_target}/advice")
    assert (empty.status_code, empty.content) == (204, b"")


def test_router_answers_500_not_204_when_the_advice_fails(world, map_id, client, monkeypatch):
    """계산 실패는 "조언 없음"(204)과 다르다 — 500 INTERNAL_ERROR로 끝나고 저장하지 않아 다시 열면 다시 만든다(#750)."""
    run_id = make_run(world, map_id)
    with monkeypatch.context() as m:
        m.setattr(core, "choose_run_advice", _boom)
        r = client("u1").get(f"/runs/{run_id}/advice")

    assert (r.status_code, r.json()["code"]) == (500, "INTERNAL_ERROR")
    assert OWN_TEXT not in r.text
    assert advice_rows(world, run_id) == []
    assert client("u1").get(f"/runs/{run_id}/advice").status_code == 200


def test_router_returns_the_spec_shape(world, map_id, client, places):
    places.places = SOFT
    run_id = make_run(world, map_id)

    first = client("u1").get(f"/runs/{run_id}/advice")
    again = client("u1").get(f"/runs/{run_id}/advice")

    assert first.status_code == 200 and _spec_errors("RunAdvice", first.json()) == []
    assert again.json() == first.json() and len(advice_runs(world, map_id)) == 1
    assert all(s not in first.text for s in SECRETS)


def test_advice_row_keeps_the_map_for_purge(world, map_id):
    run_id = make_run(world, map_id)
    advise(world, run_id)

    with world.factory() as db:
        assert db.execute(select(AgentRunAdvice.map_id).where(AgentRunAdvice.run_id == uuid.UUID(run_id))).scalar_one() == map_id

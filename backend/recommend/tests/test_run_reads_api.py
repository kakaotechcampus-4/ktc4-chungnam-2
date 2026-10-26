"""recommend.api의 추천 막힘 조언 전용 함수(#585, docs/agent-v2.md 9절·10절) — run 조회 3종과 읽기 전용 시뮬레이션.
실제 PostgreSQL이 필요하다(conftest.py)."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from common.errors import AppError
from common.events import EventLog
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from places.schemas import FactLabel
from recommend import api, core, deps, flows, service
from recommend.models import Candidate, EvidenceLine, Exclusion, RecommendRun, Region
from recommend.ports import PlaceStub


class _FakePlaceSearch:
    """반경과 무관하게 같은 풀을 돌려준다 — 반경 판정은 _run_pipeline의 반경 단계가 한다."""

    def __init__(self, places):
        self._places = places

    def search_nearby(self, *, category, circles):
        return self._places

    def get_names(self, place_ids):
        return {}


class _FakePlaceFacts:
    def __init__(self, facts_by_place):
        self._facts = facts_by_place

    def get_facts(self, place_ids):
        return {pid: [FactLabel(k, v, "known") for k, v in self._facts.get(pid, {}).items()] for pid in place_ids}


def _run(db_session, **overrides):
    values = {"id": uuid.uuid4(), "map_id": "map_1", "category": "카페", "requested_by": "user_1", "status": "collecting_evidence"}
    values.update(overrides)
    run = RecommendRun(**values)
    db_session.add(run)
    db_session.flush()
    return run


def _line(author, badge, fact_key, wants, text, **extra):
    return {"author_id": author, "source": "reaction", "text": text, "badge": badge, "fact_key": fact_key, "wants": wants, **extra}


# 반경 1000m 원 하나. far는 약 1500m 밖이라 반경 배율 2배에서만 들어온다.
PLACES = [
    PlaceStub(place_id="ok", lat=35.0005, lng=129.0005),
    PlaceStub(place_id="crowded", lat=35.0004, lng=129.0005),
    PlaceStub(place_id="narrow", lat=35.0005, lng=129.0004),
    PlaceStub(place_id="far", lat=35.0135, lng=129.0),
    PlaceStub(place_id="no_rec", lat=35.0003, lng=129.0003, can_recommend=False),
    PlaceStub(place_id="proposed", lat=35.0006, lng=129.0006),
    PlaceStub(place_id="disliked", lat=35.0002, lng=129.0002),
]
FACTS = {
    "ok": {"is_crowded_large": False, "spacious": True},
    "crowded": {"is_crowded_large": True, "spacious": True},
    "narrow": {"is_crowded_large": False, "spacious": False},
    "far": {"is_crowded_large": False, "spacious": True},
    "proposed": {"is_crowded_large": False, "spacious": True},
    "disliked": {"is_crowded_large": False, "spacious": True},
}


def _scenario(db_session):
    """실격 두 줄(남의 붐빔, 내 「좁아요」), 비활성 선호 한 줄, 이미 제안한 곳, 요청자가 🚫한 핀이 있는 run."""
    run = _run(db_session)
    db_session.add(Region(
        run_id=run.id, signature="sig", label="기본 반경", center_lat=35.0, center_lng=129.0,
        radius_m=1000, anchor_points=[[35.0, 129.0]], confirmed=True,
    ))
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        _line("user_2", "required", "is_crowded_large", None, "너무 붐벼요"),
        _line("user_1", "required", "spacious", True, "좁아요", chip_id="cafe_narrow"),
        _line("user_1", "preferred", "quiet", True, "조용한 곳", is_active=False),
    ])
    service.add_exclusions(
        db_session, map_id="map_1", category="카페", place_ids=["proposed"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )
    pin = PinRow(
        id=uuid.uuid4(), map_id="map_1", category="카페", kind="일반", origin="direct", place_id="disliked",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0002, 35.0002), 4326), visibility="public", created_by="user_2",
    )
    db_session.add(pin)
    db_session.flush()
    db_session.add(ReactionRow(pin_id=pin.id, user_id="user_1", type="against", reason_text="별로예요"))
    db_session.flush()
    lines = {line.text: str(line.id) for line in service.list_evidence(db_session, str(run.id))}
    return run, lines


def _gateways():
    return {"place_search": _FakePlaceSearch(PLACES), "place_facts": _FakePlaceFacts(FACTS)}


def _removed(funnel):
    return {entry["label"]: entry["removed_count"] for entry in funnel}


def _snapshot(db_session):
    """recommend 테이블 전부와 event_log의 행 그대로. 세션에 쓰지 않은 변경이 남아 있어도 안 된다."""
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    return {
        model.__tablename__: sorted(
            (tuple(str(v) for v in row) for row in db_session.execute(select(*model.__table__.columns)).all()),
        )
        for model in (RecommendRun, Candidate, EvidenceLine, Region, Exclusion, EventLog)
    }


# ---------- execute_run 회귀(_run_pipeline 리팩터링, #585) ----------


def test_execute_run_result_is_unchanged_by_the_pipeline_refactor(db_session):
    run, _ = _scenario(db_session)

    flows.execute_run(db_session, run_id=str(run.id), **_gateways())

    assert [c.place_id for c in service.list_candidates(db_session, str(run.id))] == ["ok"]
    assert run.last_funnel == [
        {"label": "카테고리 후보 풀", "removed_count": 0},
        {"label": "반경 밖 제거", "removed_count": 1},
        {"label": "영업 종료 제거", "removed_count": 0},
        {"label": "추천 가능 아님 제거", "removed_count": 1},
        {"label": "실격 조건 제거", "removed_count": 2},
        {"label": "이미 제안·거절됨", "removed_count": 2},
        {"label": "상위 3곳 선정", "removed_count": 0},
    ]
    dismissed = db_session.execute(select(Exclusion.place_id).where(Exclusion.reason == "dismissed")).scalars().all()
    assert dismissed == ["disliked"]  # 실행은 지금처럼 🚫한 곳을 제외 목록에 쌓는다


# ---------- get_recent_runs ----------


def _at(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


def test_get_recent_runs_lists_same_requester_and_category_newest_first(db_session):
    old = _run(db_session, status="done", created_at=_at(1))
    new = _run(db_session, status="executing", created_at=_at(3))
    _run(db_session, requested_by="user_2", created_at=_at(4))  # 남의 run
    _run(db_session, category="음식점", created_at=_at(5))  # 다른 카테고리
    db_session.add_all([
        Candidate(run_id=old.id, place_id="a", lat=35.0, lng=129.0, rank=1),
        Candidate(run_id=old.id, place_id="b", lat=35.0, lng=129.0, rank=2),
        Candidate(run_id=new.id, place_id="c", lat=35.0, lng=129.0, rank=1),
    ])
    db_session.flush()

    runs = api.get_recent_runs(db_session, run_id=str(old.id))

    assert runs == [
        {"run_id": str(new.id), "status": "executing", "result_count": 0, "created_at": _at(3)},  # done 전이라 0
        {"run_id": str(old.id), "status": "done", "result_count": 2, "created_at": _at(1)},
    ]


def test_get_recent_runs_respects_limit(db_session):
    runs = [_run(db_session, created_at=_at(day)) for day in (1, 2, 3)]

    assert [r["run_id"] for r in api.get_recent_runs(db_session, run_id=str(runs[0].id), limit=2)] == [
        str(runs[2].id), str(runs[1].id),
    ]


def test_run_reads_raise_not_found_for_unknown_run(db_session):
    for read in (api.get_run_meta, api.get_recent_runs, api.get_run_funnel, api.get_run_evidence, api.simulate_filter):
        with pytest.raises(AppError) as exc:
            read(db_session, run_id=str(uuid.uuid4()))
        assert exc.value.code == "NOT_FOUND"


# ---------- get_run_funnel ----------


def test_get_run_funnel_returns_the_last_execution_including_the_can_recommend_step(db_session):
    run, _ = _scenario(db_session)
    assert api.get_run_funnel(db_session, run_id=str(run.id)) == {"result_count": 0, "funnel": [], "passed_count": 0}  # 실행 전

    flows.execute_run(db_session, run_id=str(run.id), **_gateways())
    result = api.get_run_funnel(db_session, run_id=str(run.id))
    funnel = result["funnel"]

    assert (result["result_count"], result["passed_count"]) == (1, 1)
    assert funnel == run.last_funnel
    assert _removed(funnel)["추천 가능 아님 제거"] == 1
    funnel[0]["removed_count"] = 99
    assert run.last_funnel[0]["removed_count"] == 0  # 사본


# ---------- passed_count (#587) ----------
# 필터를 모두 통과한 곳의 수(상위 3곳을 고르기 전). 아래 판은 _scenario에 조건을 모두 통과하는 곳 넷을 더해 통과가 다섯(ok와
# ok2~ok5)이고 결과는 3곳이다. 「좁아요」를 끄면 narrow가 풀려 여섯이 된다.

MORE = [PlaceStub(place_id=f"ok{i}", lat=35.0003, lng=129.0004) for i in range(2, 6)]
PASSING = {"ok", *(p.place_id for p in MORE)}


def _gateways_with_more():
    return {
        "place_search": _FakePlaceSearch(PLACES + MORE),
        "place_facts": _FakePlaceFacts({**FACTS, **{p.place_id: FACTS["ok"] for p in MORE}}),
    }


def _passed_counts(db_session, run, lines):
    flows.execute_run(db_session, run_id=str(run.id), **_gateways_with_more())
    stored = api.get_run_funnel(db_session, run_id=str(run.id))
    sim = api.simulate_filter(db_session, run_id=str(run.id), disable_line_ids=[lines["좁아요"]], **_gateways_with_more())
    return stored, sim


def test_passed_count_is_the_number_that_passed_every_filter_before_the_top_three(db_session):
    run, lines = _scenario(db_session)

    stored, sim = _passed_counts(db_session, run, lines)

    assert len(service.list_candidates(db_session, str(run.id))) == 3   # 결과는 3곳에서 잘린다
    assert (stored["result_count"], stored["passed_count"]) == (3, len(PASSING))
    assert sim["before"]["passed_count"] == len(PASSING)
    assert (sim["after"]["result_count"], sim["after"]["passed_count"]) == (3, len(PASSING) + 1)   # narrow가 풀린다


def test_passed_count_does_not_depend_on_the_stage_label(db_session, monkeypatch):
    """깔때기 라벨 문구를 바꿔도 통과 수는 같다 — 라벨을 정하는 곳과 세는 곳이 recommend 한 곳이다."""
    monkeypatch.setattr(core, "RANKING_STAGE", "추천 3곳 고르기")
    run, lines = _scenario(db_session)

    stored, sim = _passed_counts(db_session, run, lines)

    assert stored["funnel"][-1]["label"] == "추천 3곳 고르기"
    assert (stored["passed_count"], sim["before"]["passed_count"], sim["after"]["passed_count"]) == (
        len(PASSING), len(PASSING), len(PASSING) + 1,
    )


# ---------- get_run_evidence ----------


def test_get_run_evidence_returns_every_line_in_canonical_order(db_session):
    run, lines = _scenario(db_session)

    evidence = api.get_run_evidence(db_session, run_id=str(run.id))

    assert evidence == [
        {"line_id": lines["너무 붐벼요"], "text": "너무 붐벼요", "badge": "required", "fact_key": "is_crowded_large",
         "wants": None, "is_active": True, "author_id": "user_2", "chip_id": None,
         "enforced": True, "not_enforced_reason": None},
        {"line_id": lines["좁아요"], "text": "좁아요", "badge": "required", "fact_key": "spacious",
         "wants": True, "is_active": True, "author_id": "user_1", "chip_id": "cafe_narrow",
         "enforced": True, "not_enforced_reason": None},
        {"line_id": lines["조용한 곳"], "text": "조용한 곳", "badge": "preferred", "fact_key": "quiet",
         "wants": True, "is_active": False, "author_id": "user_1", "chip_id": None,
         "enforced": True, "not_enforced_reason": None},   # 끈 줄도 켜면 쓰인다(#740)
    ]


def test_evidence_line_uses_judges_lines_without_a_run(db_session):
    _scenario(db_session)
    lines = [
        {"badge": "required", "fact_key": "is_crowded_large", "wants": None},
        {"badge": "preferred", "fact_key": "quiet", "wants": None},
        {"badge": "required", "fact_key": None, "wants": None},
    ]

    assert api.evidence_line_uses(db_session, map_id="map_1", category="카페", lines=lines) == [
        {"enforced": True, "not_enforced_reason": None},
        {"enforced": False, "not_enforced_reason": "no_direction"},
        {"enforced": False, "not_enforced_reason": "no_key"},
    ]
    assert api.evidence_line_uses(db_session, map_id="map_1", category="음식점", lines=lines[:1]) == [
        {"enforced": False, "not_enforced_reason": "not_for_category"},
    ]


# ---------- get_run_meta (#587) ----------


def test_get_run_meta_tells_who_where_and_how_far(db_session):
    run, _ = _scenario(db_session)
    before = api.get_run_meta(db_session, run_id=str(run.id))

    flows.execute_run(db_session, run_id=str(run.id), **_gateways())
    after = api.get_run_meta(db_session, run_id=str(run.id))

    assert before == {
        "run_id": str(run.id), "map_id": "map_1", "category": "카페", "requested_by": "user_1",
        "status": "collecting_evidence", "result_count": 0, "created_at": run.created_at,
        "default_radius_walk_min": 15, "widen_limit_walk_min": 30, "widen_step_walk_min": 5,
    }
    assert (after["status"], after["result_count"]) == ("done", 1)


# ---------- simulate_filter ----------


def test_simulate_before_equals_the_actual_execution(db_session):
    run, _ = _scenario(db_session)
    flows.execute_run(db_session, run_id=str(run.id), **_gateways())

    result = api.simulate_filter(db_session, run_id=str(run.id), **_gateways())

    assert result["before"] == {
        "result_count": len(service.list_candidates(db_session, str(run.id))), "funnel": run.last_funnel, "passed_count": 1,
    }
    assert result["after"] == result["before"]  # 바꾼 것이 없으면 같다


def test_simulate_turning_off_one_line_lifts_only_that_disqualification(db_session):
    run, lines = _scenario(db_session)

    result = api.simulate_filter(db_session, run_id=str(run.id), disable_line_ids=[lines["좁아요"]], **_gateways())

    before, after = _removed(result["before"]["funnel"]), _removed(result["after"]["funnel"])
    assert (before["실격 조건 제거"], after["실격 조건 제거"]) == (2, 1)  # narrow만 풀리고 crowded는 그대로 빠진다
    assert (result["before"]["result_count"], result["after"]["result_count"]) == (1, 2)
    assert {k: v for k, v in after.items() if k != "실격 조건 제거"} == {k: v for k, v in before.items() if k != "실격 조건 제거"}


def test_simulate_turning_off_an_already_inactive_line_changes_nothing(db_session):
    run, lines = _scenario(db_session)

    result = api.simulate_filter(db_session, run_id=str(run.id), disable_line_ids=[lines["조용한 곳"]], **_gateways())

    assert result["after"] == result["before"]


def test_simulate_larger_radius_factor_drops_fewer_places_at_the_radius_step(db_session):
    run, _ = _scenario(db_session)

    result = api.simulate_filter(db_session, run_id=str(run.id), radius_factor=2.0, **_gateways())

    before, after = _removed(result["before"]["funnel"]), _removed(result["after"]["funnel"])
    assert (before["반경 밖 제거"], after["반경 밖 제거"]) == (1, 0)
    assert (result["before"]["result_count"], result["after"]["result_count"]) == (1, 2)  # far가 들어온다


def test_simulate_keeps_proposed_and_dismissed_places_out(db_session, monkeypatch):
    """가드레일 6 — 반경을 넓히고 줄을 다 꺼도 이미 제안한 곳과 🚫한 곳은 돌아오지 않는다."""
    run, lines = _scenario(db_session)
    shown: set[str] = set()
    original = flows._run_pipeline

    def spy(*args, **kwargs):
        candidates_data, funnel = original(*args, **kwargs)
        shown.update(c["place_id"] for c in candidates_data)
        return candidates_data, funnel

    monkeypatch.setattr(flows, "_run_pipeline", spy)
    result = api.simulate_filter(
        db_session, run_id=str(run.id), radius_factor=3.0, disable_line_ids=list(lines.values()), **_gateways(),
    )

    assert _removed(result["after"]["funnel"])["이미 제안·거절됨"] == 2
    assert shown and shown.isdisjoint({"proposed", "disliked"})


def test_simulate_writes_nothing(db_session):
    """run·후보·근거 줄·지역·제외 목록·last_funnel·이벤트 그대로. 🚫한 곳도 제외 목록에 쌓지 않는다(실행 전 run)."""
    run, lines = _scenario(db_session)
    before = _snapshot(db_session)

    api.simulate_filter(
        db_session, run_id=str(run.id), radius_factor=2.0, disable_line_ids=[lines["좁아요"]], **_gateways(),
    )

    assert _snapshot(db_session) == before
    assert db_session.execute(select(func.count()).select_from(Exclusion).where(Exclusion.reason == "dismissed")).scalar_one() == 0


def test_simulate_writes_nothing_after_an_execution_either(db_session):
    run, lines = _scenario(db_session)
    flows.execute_run(db_session, run_id=str(run.id), **_gateways())
    db_session.flush()  # execute_run이 남긴 이벤트(record_event)를 먼저 내보낸다 — 커밋은 get_db 몫이다
    before = _snapshot(db_session)

    api.simulate_filter(db_session, run_id=str(run.id), radius_factor=2.0, disable_line_ids=[lines["너무 붐벼요"]], **_gateways())

    assert _snapshot(db_session) == before


def test_simulate_rejects_a_line_of_another_run_and_a_non_positive_factor(db_session):
    run, _ = _scenario(db_session)
    other = _run(db_session)
    service.add_reaction_evidence(db_session, run_id=other.id, lines=[_line("user_1", "required", "spacious", True, "좁아요")])
    other_line_id = str(service.list_evidence(db_session, str(other.id))[0].id)

    for bad_ids in ([other_line_id], ["not-a-uuid"]):
        with pytest.raises(AppError) as exc:
            api.simulate_filter(db_session, run_id=str(run.id), disable_line_ids=bad_ids, **_gateways())
        assert exc.value.code == "NOT_FOUND"
    for factor in (0, -1.0):
        with pytest.raises(ValueError):
            api.simulate_filter(db_session, run_id=str(run.id), radius_factor=factor, **_gateways())


def test_simulate_uses_the_same_gateways_as_execution_by_default(db_session, monkeypatch):
    run, _ = _scenario(db_session)
    monkeypatch.setattr(deps, "get_place_search_gateway", lambda: _FakePlaceSearch(PLACES))
    monkeypatch.setattr(deps, "get_place_facts_gateway", lambda: _FakePlaceFacts(FACTS))

    result = api.simulate_filter(db_session, run_id=str(run.id))

    assert result["before"]["result_count"] == 1

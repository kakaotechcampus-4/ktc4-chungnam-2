"""recommend.api.preview_filter — 미리 돌려 보기(docs/agent-v2.md 6.7, #1180). run 없이 지금 「추천 받기」를 누르면 실격 조건까지
남는 곳의 수를 센다. run을 만들 때와 같은 줄 조립, 같은 거르기를 쓰는지(같은 근거로 만든 run의 수와 같다), 제외 목록을 보지
않는지, 쓰지 않는지, 수만 돌려주는지 본다. 실제 PostgreSQL이 필요하다(conftest.py)."""

import json

import pytest
from sqlalchemy import select

from common.errors import AppError
from common.events import EventLog
from llm.schemas import EvidenceLine
from recommend import api, core, flows, service
from recommend.models import Candidate, Exclusion, RecommendRun, Region
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.ports import PlaceStub
from recommend.tests.test_flows import PLANNER, _FakePlaceFacts, _FakePlaceSearch, _make_members, _make_pin, _react

CATEGORY = "음식점"
HANSIK_TEXT = "한식 말고 고기 먹고 싶어요"
QUIET_TEXT = "조용해서 좋아요"
# ②가 냈을 줄. 🚫 글의 「고기」 원함은 #422로 선호로 내려가 아무도 거르지 않는다
HANSIK_LINES = [("cuisine_korean", False, "required"), ("cuisine_bbq", True, "required")]
QUIET_LINES = [("quiet", True, "preferred")]

# 🚫 핀(35.1, 129.0) 옆. far만 반경 밖이다. spicy·korean은 실격, 나머지 다섯 곳이 남는다(상위 3곳보다 많다)
FACTS = {
    "a": {"spicy_focused": False, "cuisine_korean": False, "quiet": True},
    "spicy": {"spicy_focused": True, "cuisine_korean": False, "quiet": True},
    "korean": {"spicy_focused": False, "cuisine_korean": True},
    "d": {"spicy_focused": False, "cuisine_korean": False, "quiet": False},
    "e": {"spicy_focused": False, "cuisine_korean": False},
    "f": {},
    "g": {"spicy_focused": False, "cuisine_korean": False, "cuisine_bbq": False},
    "far": {"spicy_focused": False},
}
PLACES = [PlaceStub(place_id=pid, lat=35.1 + 0.0001 * (i + 1), lng=129.0) for i, pid in enumerate(FACTS) if pid != "far"]
PLACES.append(PlaceStub(place_id="far", lat=35.2, lng=129.0))


def _gateways():
    return {"place_search": _FakePlaceSearch(PLACES), "place_facts": _FakePlaceFacts(FACTS)}


def _planned(raw):
    """create_run의 ② 대역 — 글마다 위의 줄을 돌려준다."""
    by_text = {HANSIK_TEXT: HANSIK_LINES, QUIET_TEXT: QUIET_LINES}
    return [
        [EvidenceLine(author_id=r["author_id"], source="reaction", text=r["text"], badge=badge, fact_key=key, wants=wants)
         for key, wants, badge in by_text[r["text"]]]
        for r in raw
    ]


def _world(db_session):
    """🚫 칩(매워요), 🚫 글(한식 말고 고기), ♥ 글(조용해서 좋아요). text_lines는 agent가 structure_reasons로 가진 ② 결과 모양이다."""
    _make_members(db_session, user_ids=["user_1", "user_2", "user_3"])
    pin = _make_pin(db_session, category=CATEGORY, lat=35.1, lng=129.0)
    _react(db_session, pin, user_id="user_1", type="against", reason_chip_ids=["food_spicy"])
    hansik = _react(db_session, pin, user_id="user_2", type="against", reason_text=HANSIK_TEXT)
    quiet = _react(db_session, pin, user_id="user_3", type="like", reason_text=QUIET_TEXT)
    text_lines = {
        str(reaction.id): [{"fact_key": key, "wants": wants, "badge": badge} for key, wants, badge in lines]
        for reaction, lines in ((hansik, HANSIK_LINES), (quiet, QUIET_LINES))
    }
    return text_lines


def _executed_run(db_session, monkeypatch):
    monkeypatch.setattr(PLANNER, "plan_evidence", _planned)
    db_session.commit()   # 요청 앞의 준비는 커밋된 상태다(#275)
    run = flows.create_run(db_session, map_id="map_1", category=CATEGORY, requested_by="user_1", evidence_planner=PLANNER)
    flows.execute_run(db_session, run_id=str(run.id), **_gateways())
    return run


def _preview(db_session, text_lines, **kwargs):
    return api.preview_filter(db_session, map_id="map_1", category=CATEGORY, text_lines=text_lines, **_gateways(), **kwargs)


def _filter_stages(funnel):
    keyed = core.keyed_funnel(funnel)
    return [{"key": e["key"], "removed_count": e["removed_count"]} for e in keyed if e["key"] in ("pool", "radius", "closed", "disqualify")]


def test_same_reasons_give_the_same_count_as_a_run_up_to_the_disqualify_step(db_session, monkeypatch):
    text_lines = _world(db_session)
    run = _executed_run(db_session, monkeypatch)
    result_count = len(service.list_candidates(db_session, str(run.id)))

    preview = _preview(db_session, text_lines)

    assert preview["funnel"] == _filter_stages(run.last_funnel)
    assert preview["funnel"] == [
        {"key": "pool", "removed_count": 0}, {"key": "radius", "removed_count": 1},
        {"key": "closed", "removed_count": 0}, {"key": "disqualify", "removed_count": 2},
    ]
    # 제외가 없는 run이라 통과 수가 같다. 결과(상위 3곳)보다 많다
    assert preview["passed_count"] == core.passed_count(result_count, core.keyed_funnel(run.last_funnel)) == 5
    assert result_count == 3


def test_a_wanted_cuisine_in_a_against_reason_is_demoted_like_in_a_run(db_session):
    """#422 — 🚫 글의 「고기」 원함은 선호라 cuisine_bbq가 거짓인 g도 남는다. 줄 조립을 run과 같은 함수로 해서다."""
    text_lines = _world(db_session)
    only_spicy_and_korean = {"a", "d", "e", "f", "g"}

    preview = _preview(db_session, text_lines, with_keys=["cuisine_bbq"])

    assert preview["passed_count"] == len(only_spicy_and_korean)
    assert preview["with_keys_count"] == 0   # 고기구이가 참인 곳은 없다(g는 거짓, 나머지는 모름)


def test_exclusions_are_neither_read_nor_applied(db_session, monkeypatch):
    """제외 목록은 사람마다 따로라 비공개다(agent-v2 2절 2번). run에서 빠지는 곳도 미리 돌려 보기에는 남는다."""
    text_lines = _world(db_session)
    run = _executed_run(db_session, monkeypatch)
    service.add_exclusions(
        db_session, map_id="map_1", category=CATEGORY, place_ids=["a", "d"], reason="proposed", run_id=run.id,
        requested_by="user_1",
    )
    after = api.simulate_filter(db_session, run_id=str(run.id), **_gateways())["before"]
    assert after["passed_count"] == 3   # run은 제안한 두 곳을 뺀다

    def no_exclusions(*args, **kwargs):
        raise AssertionError("미리 돌려 보기는 제외 목록을 읽지 않는다")

    monkeypatch.setattr(flows, "_excluded_place_ids", no_exclusions)
    monkeypatch.setattr(service, "list_excluded_place_ids", no_exclusions)
    monkeypatch.setattr(flows.pins_api, "list_disliked_place_ids", no_exclusions)

    assert _preview(db_session, text_lines)["passed_count"] == 5


def test_with_keys_counts_only_places_whose_labels_are_all_known_true(db_session):
    text_lines = _world(db_session)

    assert _preview(db_session, text_lines)["with_keys_count"] is None   # 키가 없으면 세지 않는다
    assert _preview(db_session, text_lines, with_keys=["quiet"])["with_keys_count"] == 1   # a만 참. d는 거짓, e·f·g는 모름
    assert _preview(db_session, text_lines, with_keys=["quiet", "quiet"])["with_keys_count"] == 1
    assert _preview(db_session, text_lines, with_keys=["quiet", "spicy_focused"])["with_keys_count"] == 0   # 둘 다 참이어야


def test_returns_counts_only_without_place_names_or_ids(db_session):
    text_lines = _world(db_session)

    preview = _preview(db_session, text_lines, with_keys=["quiet"])

    assert set(preview) == {"passed_count", "with_keys_count", "funnel"}
    assert all(set(entry) == {"key", "removed_count"} for entry in preview["funnel"])
    dumped = json.dumps(preview, ensure_ascii=False)
    assert not any(f'"{pid}"' in dumped for pid in FACTS)
    assert "이름-" not in dumped   # 가짜 검색의 장소 이름


def test_writes_nothing(db_session):
    text_lines = _world(db_session)
    db_session.flush()
    tables = (RecommendRun, Candidate, EvidenceLineRow, Region, Exclusion, EventLog)
    before = {m.__tablename__: db_session.execute(select(*m.__table__.columns)).all() for m in tables}

    _preview(db_session, text_lines, with_keys=["quiet"])

    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert {m.__tablename__: db_session.execute(select(*m.__table__.columns)).all() for m in tables} == before


def test_a_text_reaction_without_its_structured_lines_is_rejected(db_session):
    """② 결과가 빠진 글을 빼고 세면 run과 다른 수가 된다 — 세지 않고 알린다."""
    text_lines = _world(db_session)
    missing = dict(list(text_lines.items())[:1])

    with pytest.raises(ValueError):
        _preview(db_session, missing)


def test_rejects_a_category_that_cannot_be_recommended_and_a_map_that_is_not_ready(db_session):
    text_lines = _world(db_session)

    with pytest.raises(ValueError):
        api.preview_filter(db_session, map_id="map_1", category="숙소", text_lines=text_lines, **_gateways())
    with pytest.raises(AppError) as exc_info:
        api.preview_filter(db_session, map_id="map_1", category="카페", text_lines={}, **_gateways())
    assert exc_info.value.code == "NOT_READY"   # 카페에는 의견 핀이 없다 — run도 만들 수 없다

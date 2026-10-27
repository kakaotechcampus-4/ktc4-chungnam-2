"""카카오맵 검색 링크(#798, #800) — 결과가 적을 때, 결과 없음, 추천 준비, 결과 카드 링크.

규칙은 docs/constraints.md 「카카오맵 검색 링크」. 표 값과 문서 표가 같은지는 integration/test_policy_tables.py가 본다 —
여기서는 표에 있는 키와 없는 키를 constraints 표에서 꺼내 쓰고 말을 다시 적지 않는다.
"""

import uuid

import pytest
from sqlalchemy import func

from authz.core import Principal
from common.errors import AppError
from maps.models import Map as MapRow
from places import api as places_api
from places.schemas import PlaceInfo
from recommend import constraints, core, flows, schemas, service
from recommend.tests.test_flows import _make_candidate, _make_members, _make_pin, _make_region, _make_run, _react

CATEGORY = "음식점"
CATEGORY_WORD = constraints.CATEGORY_SEARCH_WORDS[CATEGORY]
IN_TABLE = "cuisine_korean"            # 조건 말 표에 있는 soft 키
IN_TABLE_2 = "long_established"
NOT_IN_TABLE = "quiet"                 # soft 키지만 조건 말 표에 없다(꾸밈말이라 결과가 거의 없다)
SEASONAL = "cherry_blossom"            # 조건 말 표에 있는 계절 키
AUTHOR = Principal(user_id="user_1", map_id="map_1", role="member")


def _query(lines, *, area="성수동", off_season=frozenset()):
    return core.external_search_query(area, CATEGORY, lines, off_season)


# ---------- 검색어 (core.external_search_query) ----------

def test_wanted_condition_in_table_replaces_category_word():
    assert _query([("preferred", IN_TABLE, True)]) == f"성수동 {constraints.CONDITION_SEARCH_WORDS[IN_TABLE]}"


def test_without_conditions_uses_category_word():
    assert _query([]) == f"성수동 {CATEGORY_WORD}"


def test_key_not_in_table_is_not_used_even_if_wanted():
    assert NOT_IN_TABLE in constraints.SOFT_FACT_KEYS and NOT_IN_TABLE not in constraints.CONDITION_SEARCH_WORDS
    assert _query([("preferred", NOT_IN_TABLE, True)]) == f"성수동 {CATEGORY_WORD}"


@pytest.mark.parametrize("wants", [False, None])
def test_not_wanted_or_unknown_direction_is_not_used(wants):
    """「한식 말고」(wants=False)로 한식을 찾지 않는다. 방향을 모르는 줄도 쓰지 않는다."""
    assert _query([("required", IN_TABLE, wants)]) == f"성수동 {CATEGORY_WORD}"


def test_line_without_key_is_not_used():
    assert _query([("required", None, True)]) == f"성수동 {CATEGORY_WORD}"


def test_only_one_word_first_in_evidence_order():
    """말은 하나다 — 카카오 검색은 말이 모두 맞아야 찾는다. 근거 줄 순서로 첫째."""
    lines = [("preferred", NOT_IN_TABLE, True), ("preferred", IN_TABLE_2, True), ("required", IN_TABLE, True)]
    assert _query(lines) == f"성수동 {constraints.CONDITION_SEARCH_WORDS[IN_TABLE_2]}"


def test_line_not_used_this_run_is_skipped():
    """쓰이는 줄인지는 core.evidence_line_use가 정한다 — 여행 기간 밖 계절 키는 이번 추천에 안 쓰인다."""
    lines = [("preferred", SEASONAL, True), ("preferred", IN_TABLE, True)]
    assert _query(lines, off_season=frozenset({SEASONAL})) == f"성수동 {constraints.CONDITION_SEARCH_WORDS[IN_TABLE]}"
    assert _query(lines) == f"성수동 {constraints.CONDITION_SEARCH_WORDS[SEASONAL]}"


def test_without_area_only_the_word():
    assert _query([], area=None) == CATEGORY_WORD


def test_too_long_area_is_dropped_to_fit_the_query_limit():
    assert _query([], area="가" * core.EXTERNAL_SEARCH_QUERY_MAX) == CATEGORY_WORD


def test_most_common_area_ignores_none_and_breaks_ties_by_name():
    assert core.most_common_area(["성동구 성수동1가", None, "성동구 성수동2가", "성동구 성수동2가"]) == "성동구 성수동2가"
    assert core.most_common_area(["춘천시 효자동", "춘천시 근화동"]) == "춘천시 근화동"
    assert core.most_common_area([None]) is None


# ---------- 게이트웨이 대역 ----------

class _Places:
    """후보 응답·검색어의 동네가 읽는 places 정보와 정예 장소 수. 받은 원을 남긴다."""

    def __init__(self, infos=(), curated=0):
        self._infos = {info.place_id: info for info in infos}
        self._curated = curated
        self.curated_circles = []

    def search_nearby(self, *, category, circles):
        return []

    def get_places(self, place_ids):
        return {pid: self._infos[pid] for pid in place_ids if pid in self._infos}

    def count_curated(self, *, category, circles):
        self.curated_circles.append(list(circles))
        return self._curated


def _info(place_id, *, name="가게", address="서울특별시 성동구 연무장길 1 (성수동2가)", category=CATEGORY, url=None):
    return PlaceInfo(place_id, name, 37.54, 127.05, category, kakao_place_url=url, address=address)


def _search(query):
    return {"query": query, "url": places_api.kakao_search_url(query)}


def _set_region_label(db_session, label, *, map_id="map_1"):
    row = db_session.get(MapRow, map_id)
    row.region_label = label
    row.region_center = func.ST_SetSRID(func.ST_MakePoint(127.05, 37.54), 4326)
    db_session.flush()


# ---------- 추천 준비(readiness) ----------

def test_readiness_counts_curated_within_widen_limit_of_default_region(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category=CATEGORY, lat=37.5, lng=127.0)
    _react(db_session, pin, user_id="user_1")
    places = _Places(curated=4)

    readiness = flows.get_readiness(db_session, map_id="map_1", place_search=places)

    assert readiness[CATEGORY] == {"ready": True, "answered_count": 1, "required_count": 1, "curated_nearby": 4}
    [[circle]] = places.curated_circles
    assert (circle.anchor_lat, circle.anchor_lng) == (pytest.approx(37.5), pytest.approx(127.0))
    assert circle.radius_m == core.radius_m_for_walk_min(core.WIDEN_LIMIT_MIN)   # 기본 반경 × 넓히기 상한 배율


def test_readiness_without_curated_gives_search_link_with_pin_area(db_session):
    _make_members(db_session, user_ids=["user_1"])
    pin = _make_pin(db_session, category=CATEGORY)
    _react(db_session, pin, user_id="user_1")
    places = _Places(infos=[_info(pin.place_id)], curated=0)

    readiness = flows.get_readiness(db_session, map_id="map_1", place_search=places)

    assert readiness[CATEGORY]["curated_nearby"] == 0
    assert readiness[CATEGORY]["external_search"] == _search(f"성동구 성수동2가 {CATEGORY_WORD}")


def test_readiness_without_opinion_pin_has_neither(db_session):
    _make_members(db_session, user_ids=["user_1"])
    _make_pin(db_session, category=CATEGORY)   # 의견 없는 핀
    places = _Places(curated=0)

    readiness = flows.get_readiness(db_session, map_id="map_1", place_search=places)

    assert readiness[CATEGORY] == {"ready": False, "answered_count": 0, "required_count": 1}
    assert places.curated_circles == []


# ---------- 검색어의 동네 ----------

def test_area_is_most_common_neighborhood_of_category_pins(db_session):
    _make_members(db_session, user_ids=["user_1"])
    _set_region_label(db_session, "서울")
    pins = [_make_pin(db_session, category=CATEGORY) for _ in range(3)]
    cafe = _make_pin(db_session, category="카페")
    places = _Places(infos=[
        _info(pins[0].place_id, address="서울특별시 성동구 아차산로 1 (성수동1가)"),
        _info(pins[1].place_id), _info(pins[2].place_id),
        _info(cafe.place_id, address="서울특별시 마포구 와우산로 1 (서교동)", category="카페"),   # 다른 카테고리는 안 센다
    ])

    assert flows._search_area(db_session, map_id="map_1", category=CATEGORY, place_search=places) == "성동구 성수동2가"


def test_area_falls_back_to_map_region_label_then_none(db_session):
    _make_members(db_session, user_ids=["user_1"])
    assert flows._search_area(db_session, map_id="map_1", category=CATEGORY, place_search=_Places()) is None
    _set_region_label(db_session, "춘천")
    assert flows._search_area(db_session, map_id="map_1", category=CATEGORY, place_search=_Places()) == "춘천"


# ---------- 결과(RecommendResult, NO_RESULTS) ----------

def _done_run(db_session, *, candidates):
    _make_members(db_session, user_ids=["user_1"])
    _set_region_label(db_session, "춘천")
    run = _make_run(db_session, category=CATEGORY, status="done")
    region = _make_region(db_session, run)
    run.last_funnel = [{"label": "반경 밖 제거", "removed_count": 2}]
    rows = [_make_candidate(db_session, run, rank=i + 1, region_id=region.id) for i in range(candidates)]
    return run, rows


def _wanted_line(db_session, run, fact_key, wants=True):
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[{
        "author_id": "user_1", "source": "reaction", "text": "사유 원문은 링크에 안 들어간다", "badge": "preferred",
        "fact_key": fact_key, "wants": wants,
    }])


@pytest.mark.parametrize("count", range(1, schemas.FEW_RESULTS))
def test_few_results_carry_search_link_from_wanted_condition(db_session, count):
    run, _rows = _done_run(db_session, candidates=count)
    _wanted_line(db_session, run, IN_TABLE)

    result = flows.get_result(db_session, run_id=str(run.id), principal=AUTHOR, place_search=_Places())

    assert result.external_search.model_dump() == _search(f"춘천 {constraints.CONDITION_SEARCH_WORDS[IN_TABLE]}")
    assert "사유" not in result.external_search.query


def test_enough_results_have_no_search_link(db_session):
    run, _rows = _done_run(db_session, candidates=schemas.FEW_RESULTS)

    result = flows.get_result(db_session, run_id=str(run.id), principal=AUTHOR, place_search=_Places())

    assert result.external_search is None


def test_no_results_detail_carries_funnel_and_search_link(db_session):
    run, _rows = _done_run(db_session, candidates=0)
    _wanted_line(db_session, run, IN_TABLE, wants=False)   # 「한식 말고」 — 카테고리 말로 찾는다

    with pytest.raises(AppError) as exc_info:
        flows.get_result(db_session, run_id=str(run.id), principal=AUTHOR, place_search=_Places())

    assert exc_info.value.code == "NO_RESULTS"
    assert exc_info.value.detail == {
        "funnel": [{"label": "반경 밖 제거", "removed_count": 2}],
        "external_search": _search(f"춘천 {CATEGORY_WORD}"),
    }


def test_inactive_line_is_not_used_for_the_word(db_session):
    run, _rows = _done_run(db_session, candidates=1)
    _wanted_line(db_session, run, IN_TABLE)
    for line in service.list_evidence(db_session, str(run.id)):
        service.set_evidence_active(db_session, line.id, False)

    result = flows.get_result(db_session, run_id=str(run.id), principal=AUTHOR, place_search=_Places())

    assert result.external_search.query == f"춘천 {CATEGORY_WORD}"


# ---------- 결과 카드 링크(Candidate.place_url) ----------

def test_candidate_card_link_is_kakao_page_or_name_area_search(db_session):
    run, (recorded, unrecorded, unknown) = _done_run(db_session, candidates=3)
    kakao_page = "https://place.map.kakao.com/123"
    places = _Places(infos=[
        _info(recorded.place_id, name="기록된 집", url=kakao_page),
        _info(unrecorded.place_id, name="성수 국밥"),
    ])

    result = flows.get_result(db_session, run_id=str(run.id), principal=AUTHOR, place_search=places)

    links = {c.id: c.place_url for c in result.candidates}
    assert links[str(recorded.id)] == kakao_page
    assert links[str(unrecorded.id)] == places_api.kakao_search_url("성수 국밥 성동구 성수동2가")
    assert links[str(unknown.id)] is None   # places에 없는 장소 — 필드를 생략한다
    assert {c.place_name for c in result.candidates} == {"기록된 집", "성수 국밥", None}


def test_candidates_ready_event_carries_the_same_link(db_session):
    """run.candidates_ready도 Candidate 모양 그대로다 — 응답과 같은 _candidate_response로 만든다."""
    run, (candidate,) = _done_run(db_session, candidates=1)
    places = _Places(infos=[_info(candidate.place_id, name="성수 국밥")])

    event = flows._candidates_ready_event(db_session, run, [candidate], places)

    assert event.payload["candidates"][0]["place_url"] == places_api.kakao_search_url("성수 국밥 성동구 성수동2가")


def test_place_search_gateways_expose_places_and_curated_count():
    """dev 스텁은 search_nearby가 지어내는 자리 수를 정예 수로 답하고, 합성 id라 장소 정보는 없다."""
    from recommend.deps import DevPlaceSearchGateway
    from recommend.ports import Circle

    dev = DevPlaceSearchGateway()
    circle = Circle(anchor_lat=37.5, anchor_lng=127.0, radius_m=2400)
    assert dev.count_curated(category=CATEGORY, circles=[circle]) == len(dev.search_nearby(category=CATEGORY, circles=[circle]))
    assert dev.get_places([str(uuid.uuid4())]) == {}

"""#190 — recommend가 후보·이름·라벨을 자체 장소 DB(places.api)에서만 읽는다.

1) places.testing.FakePlaces(메모리 대역)로 — 라벨 없음/unknown은 unknown_policy 그대로, 이름은 places에서.
2) places.api의 실제 구현(PostgreSQL+PostGIS, 적재 픽스처)으로 — 같은 흐름이 실제 DB에서도 돈다.
어느 쪽이든 요청 중 llm.label_place는 불리지 않는다.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from authz.core import Principal
from places import load
from places.models import Place
from places.testing import FakePlaces
from recommend import flows, service
from recommend.deps import RealPlaceFactsGateway, RealPlaceSearchGateway
from recommend.tests.test_flows import _make_members, _make_region, _make_run

FIXTURES = Path(__file__).resolve().parents[1] / "places" / "tests" / "fixtures"
CONSTRAINTS = Path(__file__).resolve().parents[2] / "docs" / "constraints.md"
SEONGSU = dict(center_lat=37.5445, center_lng=127.0561, radius_m=1000)


@pytest.fixture()
def no_label_place(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(flows.llm_service, "label_place", lambda *a, **k: calls.append((a, k)) or [])
    return calls


def _setup_run(db_session, *, required_fact_key: str | None):
    run = _make_run(db_session, status="collecting_evidence")
    _make_members(db_session, user_ids=["user_1"])
    _make_region(db_session, run, **SEONGSU)
    if required_fact_key:
        service.add_reaction_evidence(db_session, run_id=run.id, lines=[
            {"author_id": "user_1", "source": "reaction", "text": "빼주세요", "badge": "required", "fact_key": required_fact_key},
        ])
    return run


# ---------- 1) FakePlaces ----------

def test_fake_places_unknown_safety_label_is_excluded_known_pass_is_kept(db_session, monkeypatch, no_label_place):
    fake = FakePlaces().install(monkeypatch)
    run = _setup_run(db_session, required_fact_key="spicy_focused")

    flows.execute_run(db_session, run_id=str(run.id),
                      place_search=RealPlaceSearchGateway(), place_facts=RealPlaceFactsGateway())

    # 성수 칼국수: spicy_focused=False(known) → 통과 / 어묵나라: 라벨 없음 → unknown + 안전 조건(exclude) → 제거
    candidates = service.list_candidates(db_session, str(run.id))
    assert [c.place_id for c in candidates] == [fake.place_id("seongsu-kalguksu")]
    spicy = next(c for c in candidates[0].checks if c["fact_key"] == "spicy_focused")
    assert spicy["confidence"] == "known" and spicy["passed"] is True
    assert no_label_place == []


def test_fake_places_pass_policy_unknown_stays_with_needs_check(db_session, monkeypatch, no_label_place):
    fake = FakePlaces().install(monkeypatch)
    run = _setup_run(db_session, required_fact_key="is_crowded_large")   # 음식점엔 적용 안 되는 키 → 활성 실격 없음

    flows.execute_run(db_session, run_id=str(run.id),
                      place_search=RealPlaceSearchGateway(), place_facts=RealPlaceFactsGateway())

    ids = {c.place_id for c in service.list_candidates(db_session, str(run.id))}
    assert ids == {fake.place_id("seongsu-kalguksu"), fake.place_id("seongsu-bunsik")}   # 닫힌 가게·먼 곳은 places가 안 준다


def test_candidate_name_and_coordinates_come_from_places(db_session, monkeypatch, no_label_place):
    fake = FakePlaces().install(monkeypatch)
    run = _setup_run(db_session, required_fact_key=None)
    flows.execute_run(db_session, run_id=str(run.id),
                      place_search=RealPlaceSearchGateway(), place_facts=RealPlaceFactsGateway())

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    result = flows.get_result(db_session, run_id=str(run.id), principal=principal, place_search=RealPlaceSearchGateway())

    names = {c.place_name for c in result.candidates}
    assert names == {"성수 칼국수", "어묵나라 성수점"}
    stored = {c.place_id: (c.lat, c.lng) for c in service.list_candidates(db_session, str(run.id))}
    info = fake.get_places(list(stored))
    assert all(stored[pid] == (info[pid].lat, info[pid].lng) for pid in stored)


# ---------- 2) places.api 실제 구현 ----------

@pytest.fixture()
def own_db(db_session):
    load.load_permit(db_session, FIXTURES / "permit_sample.csv", crs="EPSG:5174", encoding=None)
    load.load_tourapi(db_session, FIXTURES / "tourapi_items.json")
    load.load_labels(db_session, FIXTURES / "labels.csv", constraints=CONSTRAINTS, encoding=None)
    return db_session


def test_real_places_implementation_feeds_candidates_names_and_labels(own_db, no_label_place):
    run = _setup_run(own_db, required_fact_key=None)
    search, facts = RealPlaceSearchGateway(db=own_db), RealPlaceFactsGateway(db=own_db)

    flows.execute_run(own_db, run_id=str(run.id), place_search=search, place_facts=facts)

    candidates = service.list_candidates(own_db, str(run.id))
    assert candidates, "성수 근처 영업 중 음식점이 자체 DB에서 와야 한다"
    rows = {str(r.id): r for r in own_db.execute(select(Place)).scalars()}
    for candidate in candidates:
        uuid.UUID(candidate.place_id)                              # places.id(UUID)다 — 카카오 ID가 아니다
        assert candidate.place_id in rows and rows[candidate.place_id].category == "음식점"
    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    result = flows.get_result(own_db, run_id=str(run.id), principal=principal, place_search=search)
    assert {c.place_name for c in result.candidates} == {rows[c.place_id].name for c in candidates}
    assert no_label_place == []


def test_real_places_known_true_safety_label_disqualifies_and_missing_label_excludes(own_db, no_label_place):
    run = _setup_run(own_db, required_fact_key="contains_shellfish")
    flows.execute_run(own_db, run_id=str(run.id),
                      place_search=RealPlaceSearchGateway(db=own_db), place_facts=RealPlaceFactsGateway(db=own_db))

    # P001(성수 칼국수)은 contains_shellfish=known true → 실격, 나머지는 라벨이 없어 unknown → 안전 조건이라 제거
    assert service.list_candidates(own_db, str(run.id)) == []
    funnel = {e["label"]: e["removed_count"] for e in run.last_funnel}
    assert funnel["실격 조건 제거"] >= 1
    assert no_label_place == []


def test_real_places_candidates_carry_the_data_source(own_db, no_label_place):
    """#242 — 후보 응답에 places의 데이터 출처(permit|tourapi)가 붙는다(가드레일 5)."""
    run = _setup_run(own_db, required_fact_key=None)
    search, facts = RealPlaceSearchGateway(db=own_db), RealPlaceFactsGateway(db=own_db)
    flows.execute_run(own_db, run_id=str(run.id), place_search=search, place_facts=facts)

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    result = flows.get_result(own_db, run_id=str(run.id), principal=principal, place_search=search)
    assert result.candidates and all(c.place_source and c.place_source.provider == "permit" for c in result.candidates)

"""recommend/service.py — 실제 PostgreSQL이 필요하다(db_session, conftest.py 참고)."""

import uuid

import pytest

from common.errors import AppError
from recommend import service
from recommend.models import Candidate, RecommendRun


def _make_run(db_session, **overrides):
    defaults = {
        "id": uuid.uuid4(), "map_id": "map_1", "category": "음식점",
        "requested_by": "user_1", "status": "done",
    }
    defaults.update(overrides)
    run = RecommendRun(**defaults)
    db_session.add(run)
    db_session.flush()
    return run


def _make_candidate(db_session, run, **overrides):
    defaults = {
        "id": uuid.uuid4(), "run_id": run.id, "place_id": f"place_{uuid.uuid4().hex[:8]}",
        "lat": 35.1, "lng": 129.0, "rank": 1,
    }
    defaults.update(overrides)
    candidate = Candidate(**defaults)
    db_session.add(candidate)
    db_session.flush()
    return candidate


def test_load_candidate_with_run_returns_both(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)

    loaded_candidate, loaded_run = service.load_candidate_with_run(db_session, str(candidate.id))

    assert loaded_candidate.id == candidate.id
    assert loaded_run.id == run.id


def test_load_candidate_with_run_nonexistent_id_is_not_found(db_session):
    with pytest.raises(AppError) as exc_info:
        service.load_candidate_with_run(db_session, str(uuid.uuid4()))
    assert exc_info.value.code == "NOT_FOUND"


def test_load_candidate_with_run_malformed_id_is_not_found(db_session):
    with pytest.raises(AppError) as exc_info:
        service.load_candidate_with_run(db_session, "not-a-uuid")
    assert exc_info.value.code == "NOT_FOUND"


def test_link_published_pin_sets_pin_id(db_session):
    run = _make_run(db_session)
    candidate = _make_candidate(db_session, run)
    pin_id = uuid.uuid4()

    service.link_published_pin(db_session, candidate_id=str(candidate.id), pin_id=str(pin_id))

    db_session.refresh(candidate)
    assert candidate.published_pin_id == pin_id


def test_link_published_pin_guard_rejects_already_linked(db_session):
    run = _make_run(db_session)
    already_linked = uuid.uuid4()
    candidate = _make_candidate(db_session, run, published_pin_id=already_linked)

    with pytest.raises(AppError) as exc_info:
        service.link_published_pin(db_session, candidate_id=str(candidate.id), pin_id=str(uuid.uuid4()))
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"

    db_session.refresh(candidate)
    assert candidate.published_pin_id == already_linked  # 덮어써지지 않았다


# ---------- create_run / get_run_or_404 / max_attempt_no_for_requester ----------

def test_create_run_defaults_to_collecting_evidence(db_session):
    run = service.create_run(db_session, map_id="map_1", category="음식점", requested_by="user_1", attempt_no=1)
    assert run.status == "collecting_evidence"
    assert run.attempt_no == 1


def test_get_run_or_404_nonexistent_is_not_found(db_session):
    with pytest.raises(AppError) as exc_info:
        service.get_run_or_404(db_session, str(uuid.uuid4()))
    assert exc_info.value.code == "NOT_FOUND"


def test_max_attempt_no_for_requester_defaults_to_zero_with_no_runs(db_session):
    assert service.max_attempt_no_for_requester(db_session, map_id="map_1", requested_by="nobody") == 0


def test_max_attempt_no_for_requester_ignores_other_people_and_maps(db_session):
    _make_run(db_session, map_id="map_1", requested_by="user_1", attempt_no=3)
    _make_run(db_session, map_id="map_1", requested_by="user_2", attempt_no=5)
    _make_run(db_session, map_id="map_2", requested_by="user_1", attempt_no=9)
    assert service.max_attempt_no_for_requester(db_session, map_id="map_1", requested_by="user_1") == 3


# ---------- evidence_lines ----------

def test_add_reaction_evidence_and_list_evidence_round_trip(db_session):
    run = _make_run(db_session)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "매워요", "badge": "required", "fact_key": None},
    ])
    lines = service.list_evidence(db_session, str(run.id))
    assert len(lines) == 1
    assert lines[0].source == "reaction"
    assert lines[0].is_active is True


def test_add_manual_evidence_defaults_to_reference_badge(db_session):
    run = _make_run(db_session)
    line = service.add_manual_evidence(db_session, run_id=run.id, author_id="user_1", text="주차 가능하면 좋겠어요")
    assert line.source == "manual"
    assert line.badge == "reference"
    assert line.fact_key is None


def test_list_active_evidence_excludes_inactive(db_session):
    run = _make_run(db_session)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "a", "badge": "required", "fact_key": "spicy_focused"},
        {"author_id": "user_1", "source": "reaction", "text": "b", "badge": "required", "fact_key": "oily_focused",
         "is_active": False},
    ])
    active = service.list_active_evidence(db_session, run.id)
    assert [line.fact_key for line in active] == ["spicy_focused"]


def test_set_evidence_active_toggles_flag(db_session):
    run = _make_run(db_session)
    line = service.add_manual_evidence(db_session, run_id=run.id, author_id="user_1", text="x")
    service.set_evidence_active(db_session, line.id, False)
    db_session.refresh(line)
    assert line.is_active is False


def test_get_evidence_or_none_returns_none_for_malformed_id(db_session):
    assert service.get_evidence_or_none(db_session, "not-a-uuid") is None


# ---------- regions ----------

def test_create_regions_and_list_regions(db_session):
    run = _make_run(db_session)
    service.create_regions(db_session, run_id=run.id, regions_data=[{
        "signature": "sig1", "label": "기본 반경", "center_lat": 35.1, "center_lng": 129.0,
        "radius_m": 2000, "confirmed": True, "confirmed_at": None,
    }])
    regions = service.list_regions(db_session, str(run.id))
    assert len(regions) == 1
    assert regions[0].label == "기본 반경"


def test_update_region_radius_keeps_same_id(db_session):
    run = _make_run(db_session)
    [region] = service.create_regions(db_session, run_id=run.id, regions_data=[{
        "signature": "sig1", "label": "기본 반경", "center_lat": 35.1, "center_lng": 129.0,
        "radius_m": 2000, "confirmed": True, "confirmed_at": None,
    }])
    region_id = region.id
    service.update_region_radius(db_session, region, radius_m=4000, signature="sig2")
    db_session.refresh(region)
    assert region.id == region_id
    assert region.radius_m == 4000
    assert region.signature == "sig2"


def test_confirm_all_regions_sets_confirmed_and_timestamp(db_session):
    run = _make_run(db_session)
    [region] = service.create_regions(db_session, run_id=run.id, regions_data=[{
        "signature": "sig1", "label": "기본 반경", "center_lat": 35.1, "center_lng": 129.0,
        "radius_m": 2000, "confirmed": False, "confirmed_at": None,
    }])
    service.confirm_all_regions(db_session, run.id)
    db_session.refresh(region)
    assert region.confirmed is True
    assert region.confirmed_at is not None


# ---------- candidates ----------

def test_replace_unpublished_candidates_keeps_published_ones(db_session):
    run = _make_run(db_session)
    published = _make_candidate(db_session, run, published_pin_id=uuid.uuid4())
    _make_candidate(db_session, run)  # 아직 게시 안 됨 — 교체 대상

    service.replace_unpublished_candidates(db_session, run_id=run.id, candidates_data=[{
        "place_id": "new_place", "region_id": None, "lat": 1.0, "lng": 2.0, "rank": 1,
        "checks": [], "member_fulfillment": {},
    }])

    remaining = service.list_candidates(db_session, str(run.id))
    place_ids = {c.place_id for c in remaining}
    assert published.place_id in place_ids
    assert "new_place" in place_ids
    assert len(remaining) == 2


# ---------- exclusions ----------

def test_add_exclusions_and_list_excluded_place_ids(db_session):
    run = _make_run(db_session)
    service.add_exclusions(
        db_session, map_id="map_1", category="음식점", place_ids=["p1", "p2"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )
    excluded = service.list_excluded_place_ids(db_session, map_id="map_1", requested_by="user_1")
    assert excluded == {"p1", "p2"}


def test_add_exclusions_ignores_duplicate_person_place_pair(db_session):
    run = _make_run(db_session)
    service.add_exclusions(
        db_session, map_id="map_1", category="음식점", place_ids=["p1"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )
    other_run = _make_run(db_session)
    service.add_exclusions(  # 같은 (map,requester,place) 재삽입 — 조용히 무시(uq 제약)
        db_session, map_id="map_1", category="음식점", place_ids=["p1"],
        reason="dismissed", run_id=other_run.id, requested_by="user_1",
    )
    excluded = service.list_excluded_place_ids(db_session, map_id="map_1", requested_by="user_1")
    assert excluded == {"p1"}


def test_add_exclusions_is_per_requester(db_session):
    run = _make_run(db_session)
    service.add_exclusions(
        db_session, map_id="map_1", category="음식점", place_ids=["p1"],
        reason="proposed", run_id=run.id, requested_by="user_1",
    )
    assert service.list_excluded_place_ids(db_session, map_id="map_1", requested_by="user_2") == set()


# ---------- run status / funnel / attempt bump ----------

def test_set_run_status_updates_field(db_session):
    run = _make_run(db_session)
    service.set_run_status(db_session, run, "executing")
    assert run.status == "executing"


def test_set_last_funnel_stores_value(db_session):
    run = _make_run(db_session)
    funnel = [{"label": "x", "removed_count": 1}]
    service.set_last_funnel(db_session, run, funnel)
    db_session.refresh(run)
    assert run.last_funnel == funnel


def test_bump_attempt_no_increments(db_session):
    run = _make_run(db_session, attempt_no=1)
    new_value = service.bump_attempt_no(db_session, run)
    assert new_value == 2
    assert run.attempt_no == 2

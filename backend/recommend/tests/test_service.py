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

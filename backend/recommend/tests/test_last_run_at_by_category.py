"""recommend.api.last_run_at_by_category(#522) — agent는 카테고리별 마지막 run 시각만 본다(명세 2절 2번)."""

from datetime import datetime, timedelta, timezone

from recommend import api
from recommend.models import RecommendRun

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _run(db, *, map_id="map_1", category="음식점", requested_by="u1", minutes=0):
    db.add(RecommendRun(map_id=map_id, category=category, requested_by=requested_by, status="done",
                        created_at=T0 + timedelta(minutes=minutes)))
    db.flush()


def test_latest_created_at_per_category_only(db_session):
    _run(db_session, category="음식점", minutes=0)
    _run(db_session, category="음식점", requested_by="u2", minutes=30)
    _run(db_session, category="카페", minutes=10)
    _run(db_session, map_id="other_map", category="관광지", minutes=60)

    assert api.last_run_at_by_category(db_session, map_id="map_1") == {
        "음식점": T0 + timedelta(minutes=30),
        "카페": T0 + timedelta(minutes=10),
    }


def test_values_are_only_timestamps(db_session):
    """후보·근거·요청자는 돌려주지 않는다 — 값은 시각 하나뿐이다."""
    _run(db_session, requested_by="secret_requester")

    result = api.last_run_at_by_category(db_session, map_id="map_1")

    assert all(isinstance(value, datetime) for value in result.values())
    assert "secret_requester" not in repr(result)


def test_map_without_runs_returns_empty(db_session):
    assert api.last_run_at_by_category(db_session, map_id="map_1") == {}

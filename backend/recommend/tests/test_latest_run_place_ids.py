"""recommend.api.latest_run_place_ids(#646) — 추천 탭 광고가 요청자의 최신 추천 결과 장소를 뺄 때 부른다(docs/ads.md 5절 2번)."""

import uuid
from datetime import datetime, timedelta, timezone

from recommend import api
from recommend.models import Candidate, RecommendRun

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)


def _run(db, *place_ids, map_id="map_1", category="음식점", requested_by="u1", minutes=0, published=()):
    run = RecommendRun(map_id=map_id, category=category, requested_by=requested_by, status="done",
                       created_at=T0 + timedelta(minutes=minutes))
    db.add(run)
    db.flush()
    db.add_all(
        Candidate(run_id=run.id, place_id=pid, lat=37.5, lng=127.0, rank=rank,
                  published_pin_id=uuid.uuid4() if pid in published else None)
        for rank, pid in enumerate(place_ids, start=1)
    )
    db.flush()
    return run


def _ids(db, *, category=None, requested_by="u1", map_id="map_1"):
    return api.latest_run_place_ids(db, map_id=map_id, requested_by=requested_by, category=category)


def test_only_the_latest_run_of_a_category(db_session):
    _run(db_session, "old_a", "old_b", minutes=0)
    _run(db_session, "new_a", "new_b", minutes=10)

    assert _ids(db_session, category="음식점") == {"new_a", "new_b"}


def test_published_candidates_of_the_latest_run_are_included(db_session):
    _run(db_session, "kept", "shown", published=("kept",))

    assert _ids(db_session, category="음식점") == {"kept", "shown"}


def test_category_given_looks_at_that_category_only(db_session):
    _run(db_session, "food", category="음식점")
    _run(db_session, "cafe", category="카페", minutes=5)

    assert _ids(db_session, category="카페") == {"cafe"}
    assert _ids(db_session, category="관광지") == set()


def test_no_category_takes_the_latest_run_of_each_category(db_session):
    _run(db_session, "food_old", category="음식점", minutes=0)
    _run(db_session, "food_new", category="음식점", minutes=20)
    _run(db_session, "cafe_old", category="카페", minutes=5)
    _run(db_session, "cafe_new", category="카페", minutes=15)
    _run(db_session, "spot", category="관광지", minutes=1)

    assert _ids(db_session) == {"food_new", "cafe_new", "spot"}


def test_other_members_runs_are_ignored(db_session):
    _run(db_session, "mine", requested_by="u1", minutes=0)
    _run(db_session, "theirs", requested_by="u2", minutes=30)   # 더 최근이어도 요청자가 다르면 보지 않는다

    assert _ids(db_session, category="음식점") == {"mine"}
    assert _ids(db_session) == {"mine"}
    assert _ids(db_session, requested_by="u3") == set()


def test_other_maps_are_ignored(db_session):
    _run(db_session, "here", map_id="map_1", minutes=0)
    _run(db_session, "there", map_id="map_2", minutes=30)

    assert _ids(db_session) == {"here"}


def test_no_runs_is_an_empty_set(db_session):
    assert _ids(db_session) == set()
    assert _ids(db_session, category="음식점") == set()


def test_latest_run_without_candidates_is_empty_for_that_category(db_session):
    _run(db_session, "old", minutes=0)
    _run(db_session, minutes=10)   # 결과 0개 — 이전 run으로 내려가지 않는다

    assert _ids(db_session, category="음식점") == set()


def test_non_recommendable_category_is_an_empty_set(db_session):
    _run(db_session, "food")

    assert _ids(db_session, category="숙소") == set()
    assert _ids(db_session, category="기타") == set()


def test_read_only(db_session):
    _run(db_session, "a")
    _ids(db_session)

    assert not db_session.dirty and not db_session.new

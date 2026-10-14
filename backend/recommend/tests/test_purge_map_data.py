"""api.purge_map_data(#431) — 대상 지도의 추천 기록 5개 테이블만 지운다(자식 → run 순서)."""

from recommend import api
from recommend.models import Candidate, EvidenceLine, Exclusion, RecommendRun, Region

TABLES = (EvidenceLine, Candidate, Region, Exclusion, RecommendRun)


def _seed(db, map_id):
    run = RecommendRun(map_id=map_id, category="음식점", requested_by="u1", status="done")
    db.add(run)
    db.flush()
    region = Region(run_id=run.id, signature="s", label="홍대", center_lat=37.5, center_lng=126.9, radius_m=1000)
    db.add(region)
    db.flush()
    db.add(Candidate(run_id=run.id, place_id="p1", region_id=region.id, lat=37.5, lng=126.9, rank=1))
    db.add(Candidate(run_id=run.id, place_id="p2", region_id=None, lat=37.5, lng=126.9, rank=2))
    db.add(EvidenceLine(run_id=run.id, author_id="u1", source="manual", text="매운 곳", badge="required"))
    db.add(Exclusion(map_id=map_id, category="음식점", place_id="p9", reason="dismissed", run_id=run.id, requested_by="u1"))
    db.flush()


def _remaining(db):
    return {model.__tablename__: db.query(model).count() for model in TABLES}


def test_purge_deletes_only_target_maps_records(db_session):
    _seed(db_session, "gone")
    _seed(db_session, "keep")

    result = api.purge_map_data(db_session, map_ids=["gone"])

    assert result == {"evidence_lines": 1, "candidates": 2, "regions": 1, "exclusions": 1, "recommend_runs": 1}
    assert _remaining(db_session) == {name: 1 if name != "candidates" else 2 for name in _remaining(db_session)}
    assert [r.map_id for r in db_session.query(RecommendRun).all()] == ["keep"]


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    _seed(db_session, "keep")

    assert set(api.purge_map_data(db_session, map_ids=[]).values()) == {0}
    assert _remaining(db_session) == {
        "evidence_lines": 1, "candidates": 2, "regions": 1, "exclusions": 1, "recommend_runs": 1,
    }

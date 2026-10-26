"""추천 후보 여부(PlaceRef.can_recommend) — 후보 조회가 places.curated를 그대로 담는다(#743). 실제 PostgreSQL+PostGIS."""

import uuid
from pathlib import Path

from places import api, load, repository
from places.models import Place
from places.schemas import Area, PlaceRef

LAT, LNG = 37.5445, 127.0561


def _place(db, name, category="음식점", status="open", dlat=0.0, curated=False):
    p = Place(source="permit", source_id=uuid.uuid4().hex, name=name, category=category, status=status, curated=curated,
              geom=f"SRID=4326;POINT({LNG} {LAT + dlat})")
    db.add(p)
    db.flush()
    return p


def test_there_is_no_stored_can_recommend_column():
    assert "can_recommend" not in Place.__table__.c


def test_search_nearby_own_carries_curated_as_can_recommend(db_session):
    yes, no = _place(db_session, "정예", curated=True, dlat=0.0001), _place(db_session, "비정예", dlat=0.0002)
    refs = {r.place_id: r for r in api.search_nearby_own("음식점", [Area(LAT, LNG, 500)], db=db_session)}
    assert refs[str(yes.id)].can_recommend is True and refs[str(no.id)].can_recommend is False


def test_a_curated_change_is_seen_without_any_recompute(db_session):
    p = _place(db_session, "가게")
    area = [Area(LAT, LNG, 500)]
    assert api.search_nearby_own("음식점", area, db=db_session)[0].can_recommend is False
    p.curated = True
    db_session.flush()
    assert api.search_nearby_own("음식점", area, db=db_session)[0].can_recommend is True


def test_place_ref_defaults_to_true_for_existing_callers():
    assert PlaceRef("p", 1.0, 2.0).can_recommend is True
    assert PlaceRef("p", 1.0, 2.0, False).can_recommend is False


def test_search_and_nearest_ignore_the_flag(db_session):
    """검색·핀 생성 매칭·근처 장소는 추천 후보 여부와 무관하다 — 사용자가 고른 장소는 언제나 핀이 된다."""
    p = _place(db_session, "비정예 가게")
    assert [r.place_id for r in api.nearest_own_places(LAT, LNG, None, db=db_session)] == [f"own:{p.id}"]


def test_curated_counts_per_category(db_session):
    _place(db_session, "정예", curated=True)
    _place(db_session, "비정예")
    _place(db_session, "관광지", "관광지")
    counts = repository.curated_counts(db_session)
    assert counts[("음식점", True)] == 1 and counts[("음식점", False)] == 1 and counts[("관광지", False)] == 1


def test_load_reports_curated_counts_at_the_end(db_session, capsys):
    fix = Path(__file__).parent / "fixtures"
    assert load.main(["permit", "--file", str(fix / "permit_sample.csv"), "--crs", "EPSG:5174"],
                     session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "[curated] 분류별 정예 / 정예 아님" in out and "합계:" in out

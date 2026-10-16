"""can_recommend — 판정 규칙(순수), 전체 재계산(멱등·정예 보존·dry-run), PlaceRef 필드, 적재 끝 자동 재계산. 실제 PostgreSQL+PostGIS."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from places import api, core, load, repository
from places.models import Place, PlaceFact
from places.schemas import Area, PlaceRef
from places.scripts import recompute_can_recommend as recompute_script

CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"
LAT, LNG = 37.5445, 127.0561


# ---- 판정 규칙(순수 함수) ----

@pytest.mark.parametrize("category,known,curated,expected", [
    ("음식점", 4, False, False), ("음식점", 5, False, True), ("음식점", 0, False, False),
    ("카페", 2, False, False), ("카페", 3, False, True),
    ("관광지", 0, False, True),                      # 관광지는 임계 없이 true
    ("음식점", 0, True, True), ("카페", 0, True, True),   # 정예는 라벨 수와 무관하게 true
    ("숙소", 99, False, False),                      # 모르는 분류는 추천 후보에서 뺀다
])
def test_rule(category, known, curated, expected):
    assert core.can_recommend(category, known, curated=curated) is expected


def test_thresholds_live_in_one_constant(monkeypatch):
    monkeypatch.setitem(core.KNOWN_LABEL_THRESHOLDS, "음식점", 2)
    assert core.can_recommend("음식점", 2, curated=False) is True


# ---- DB 헬퍼 ----

def _place(db, name, category="음식점", status="open", dlat=0.0, labels=0, curated=False):
    """labels: 확정 라벨 수. curated면 places.curated를 켠다(정예 적재가 켜는 값)."""
    p = Place(source="permit", source_id=uuid.uuid4().hex, name=name, category=category, status=status, curated=curated,
              geom=f"SRID=4326;POINT({LNG} {LAT + dlat})")
    db.add(p)
    db.flush()
    for i in range(labels):
        db.add(PlaceFact(place_id=p.id, fact_key=f"k{i}", value=True, confidence="known", source_layer=3, label_source="license_area"))
    db.flush()
    return p


def _flag(db, place):
    db.expire_all()
    return db.get(Place, place.id).can_recommend


# ---- 재계산 ----

def test_recompute_applies_thresholds_and_reports_counts_per_category(db_session):
    few, enough = _place(db_session, "라벨 적음", labels=4), _place(db_session, "라벨 충분", labels=5)
    cafe_few, cafe_ok = _place(db_session, "카페 적음", "카페", labels=2), _place(db_session, "카페 충분", "카페", labels=3)
    sight = _place(db_session, "관광지", "관광지")
    result = repository.recompute_can_recommend(db_session)
    assert [_flag(db_session, p) for p in (few, enough, cafe_few, cafe_ok, sight)] == [False, True, False, True, True]
    assert result.counts[("음식점", True)] == 1 and result.counts[("음식점", False)] == 1
    assert result.counts[("카페", True)] == 1 and result.counts[("카페", False)] == 1 and result.counts[("관광지", True)] == 1
    assert result.changed == 3


def test_curated_rows_are_true_even_without_enough_known_labels(db_session):
    """정예(places.curated)는 확정 라벨이 적어도 true."""
    curated = _place(db_session, "정예", labels=1, curated=True)
    coverage = _place(db_session, "커버리지", labels=1)
    repository.recompute_can_recommend(db_session)
    assert _flag(db_session, curated) is True and _flag(db_session, coverage) is False


def test_recompute_is_idempotent(db_session):
    _place(db_session, "충분", labels=5)
    _place(db_session, "적음", labels=1)
    first = repository.recompute_can_recommend(db_session)
    second = repository.recompute_can_recommend(db_session)
    assert first.changed == 1 and second.changed == 0 and second.counts == first.counts


def test_recompute_follows_label_changes_both_ways(db_session):
    p = _place(db_session, "가게", labels=5)
    repository.recompute_can_recommend(db_session)
    assert _flag(db_session, p) is True
    for fact in db_session.execute(select(PlaceFact).where(PlaceFact.place_id == p.id)).scalars().all()[:2]:
        db_session.delete(fact)
    db_session.flush()
    repository.recompute_can_recommend(db_session)
    assert _flag(db_session, p) is False


def test_dry_run_changes_nothing_but_reports(db_session):
    p = _place(db_session, "충분", labels=5)
    result = repository.recompute_can_recommend(db_session, dry_run=True)
    assert result.changed == 1 and result.counts[("음식점", True)] == 1
    assert _flag(db_session, p) is False


def test_closed_places_are_computed_too(db_session):
    p = _place(db_session, "폐업", status="closed", labels=5)
    repository.recompute_can_recommend(db_session)
    assert _flag(db_session, p) is True   # 다시 열릴 때 값이 맞도록


def test_script_reports_counts_and_commits(db_session, capsys):
    pid = _place(db_session, "충분", labels=5).id
    assert recompute_script.main([], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "음식점: 1 / 0" in out and "dry-run" not in out
    assert db_session.get(Place, pid).can_recommend is True   # main이 세션을 닫았으니 id로 다시 읽는다


def test_script_dry_run_reports_but_does_not_write(db_session, capsys):
    """dry-run은 롤백한다 — 테스트 세션의 savepoint째 되돌아가므로 값이 아니라 계산·쓰기 호출 여부를 본다."""
    _place(db_session, "충분", labels=5)
    wrote = []
    real = db_session.execute
    db_session.execute = lambda stmt, *a, **kw: (wrote.append(1) if stmt.__class__.__name__ == "Update" else None) or real(stmt, *a, **kw)
    assert recompute_script.main(["--dry-run"], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "음식점: 1 / 0" in out and "dry-run" in out and "바뀔 장소 1곳" in out
    assert not wrote


def test_report_lines_format():
    result = repository.RecomputeResult({("음식점", True): 3, ("음식점", False): 1, ("카페", True): 2}, 4)
    lines = recompute_script.report_lines(result, dry_run=False)
    assert "  음식점: 3 / 1" in lines and "  카페: 2 / 0" in lines and "  합계: 5 / 1" in lines and lines[-1] == "값이 바뀐 장소 4곳"


# ---- PlaceRef ----

def test_search_nearby_own_carries_can_recommend(db_session):
    yes, no = _place(db_session, "충분", labels=5, dlat=0.0001), _place(db_session, "적음", labels=1, dlat=0.0002)
    repository.recompute_can_recommend(db_session)
    refs = {r.place_id: r for r in api.search_nearby_own("음식점", [Area(LAT, LNG, 500)], db=db_session)}
    assert refs[str(yes.id)].can_recommend is True and refs[str(no.id)].can_recommend is False


def test_place_ref_defaults_to_true_for_existing_callers():
    assert PlaceRef("p", 1.0, 2.0).can_recommend is True
    assert PlaceRef("p", 1.0, 2.0, False).can_recommend is False


def test_search_and_nearest_ignore_can_recommend(db_session):
    """검색·핀 생성 매칭·근처 장소는 can_recommend와 무관하다 — 사용자가 고른 장소는 언제나 핀이 된다."""
    p = _place(db_session, "라벨 없는 가게")
    assert _flag(db_session, p) is False
    assert [r.place_id for r in api.nearest_own_places(LAT, LNG, None, db=db_session)] == [f"own:{p.id}"]


# ---- 적재 끝 자동 재계산 ----

def test_load_recomputes_at_the_end(db_session, capsys):
    fix = Path(__file__).parent / "fixtures"
    assert load.main(["permit", "--file", str(fix / "permit_sample.csv"), "--crs", "EPSG:5174"],
                     session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "[can_recommend]" in out and "합계:" in out


def test_label_without_source_no_longer_means_curated(db_session):
    """예전 휴리스틱(출처 NULL 라벨 = 정예)은 마이그레이션 되메우기에서만 쓴다 — 재계산은 places.curated만 본다."""
    p = _place(db_session, "커버리지", labels=1)
    db_session.add(PlaceFact(place_id=p.id, fact_key="unk", value=None, confidence="unknown", source_layer=3, label_source=None))
    db_session.flush()
    repository.recompute_can_recommend(db_session)
    assert _flag(db_session, p) is False


def test_recompute_never_turns_curated_off(db_session):
    p = _place(db_session, "정예", curated=True)
    repository.recompute_can_recommend(db_session)
    repository.recompute_can_recommend(db_session)
    db_session.expire_all()
    assert db_session.get(Place, p.id).curated is True and db_session.get(Place, p.id).can_recommend is True

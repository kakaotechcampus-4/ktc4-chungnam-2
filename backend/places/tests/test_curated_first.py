"""정예 우선 정책(#507) — 정예 파일은 같은 (source, source_id)를 덮고, 인허가 커버리지는 이미 있는 장소·라벨을 건드리지 않는다. 실제 PostgreSQL+PostGIS."""

import csv
from pathlib import Path

import pytest
from sqlalchemy import select

from places import ingest, load, repository
from places.models import Place, PlaceFact

CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"


def _row(source_id, name, category, address="서울특별시 성동구 성수이로 1", source="permit"):
    return ingest.PlaceRow(source, source_id, name, category, address, None, 37.5445, 127.0561, "open")


def _label(source_id, key, value, label_source="license_business_type", confidence="known"):
    return ingest.LabelRow("permit", source_id, key, value, confidence, 3, None, "근거", label_source)


def _place(db, source_id):
    return db.execute(select(Place).where(Place.source == "permit", Place.source_id == source_id)).scalar_one()


def _facts(db, source_id):
    pid = _place(db, source_id).id
    return {f.fact_key: (f.value, f.confidence, f.label_source) for f in db.execute(select(PlaceFact).where(PlaceFact.place_id == pid)).scalars()}


# ---- 장소: 정예 파일(overwrite) ----

def test_authoritative_overwrites_name_and_category_even_when_category_differs(db_session):
    repository.upsert_places(db_session, [_row("A1", "커버리지 이름", "음식점")])
    result = repository.upsert_places(db_session, [_row("A1", "정예 이름", "카페")], existing_mode="overwrite")
    place = _place(db_session, "A1")
    assert (place.name, place.category) == ("정예 이름", "카페")
    assert (result.updated, result.name_changed, result.category_changed, result.category_kept) == (1, 1, 1, 0)


def test_authoritative_keeps_kakao_link(db_session):
    repository.upsert_places(db_session, [_row("A2", "가게", "음식점")])
    repository.record_kakao_match(db_session, str(_place(db_session, "A2").id), "k-1", "https://place.map.kakao.com/k-1")
    repository.upsert_places(db_session, [_row("A2", "정예 가게", "카페")], existing_mode="overwrite")
    assert _place(db_session, "A2").kakao_place_id == "k-1"


def test_default_mode_still_keeps_a_different_category(db_session):
    repository.upsert_places(db_session, [_row("A3", "가게", "음식점")])
    result = repository.upsert_places(db_session, [_row("A3", "다른 이름", "카페")])   # #463 기존 동작
    assert (_place(db_session, "A3").name, _place(db_session, "A3").category) == ("가게", "음식점")
    assert result.category_kept == 1


# ---- 장소: 인허가 커버리지(keep) ----

def test_cover_load_does_not_touch_existing_places_but_inserts_new_ones(db_session):
    repository.upsert_places(db_session, [_row("B1", "정예 이름", "카페")], existing_mode="overwrite")
    result = repository.upsert_places(
        db_session, [_row("B1", "커버리지 이름", "카페"), _row("B2", "새 가게", "음식점")], existing_mode="keep")
    assert _place(db_session, "B1").name == "정예 이름"
    assert _place(db_session, "B2").name == "새 가게"
    assert (result.inserted, result.updated, result.existing_kept) == (1, 0, 1)


def test_cover_load_keeps_existing_category_and_coordinates(db_session):
    repository.upsert_places(db_session, [_row("B3", "가게", "카페")], existing_mode="overwrite")
    moved = ingest.PlaceRow("permit", "B3", "가게", "음식점", "다른 주소 1", None, 37.6, 127.1, "open")
    repository.upsert_places(db_session, [moved], existing_mode="keep")
    place = _place(db_session, "B3")
    assert place.category == "카페" and place.address == "서울특별시 성동구 성수이로 1"


def test_closed_rows_still_mark_existing_places_closed_in_keep_mode(db_session):
    repository.upsert_places(db_session, [_row("B4", "가게", "음식점")])
    closed = ingest.PlaceRow("permit", "B4", "가게", "음식점", None, None, 37.5445, 127.0561, "closed")
    repository.upsert_places(db_session, [closed], existing_mode="keep")
    assert _place(db_session, "B4").status == "closed"


def test_unknown_existing_mode_is_rejected(db_session):
    with pytest.raises(ValueError):
        repository.upsert_places(db_session, [_row("B5", "가게", "카페")], existing_mode="merge")


# ---- 라벨 ----

def test_cover_labels_add_only_missing_keys(db_session):
    repository.upsert_places(db_session, [_row("C1", "가게", "카페")])
    repository.upsert_facts(db_session, [_label("C1", "quiet", True, "직접 조사")])   # 정예 라벨
    result = repository.upsert_facts(
        db_session, [_label("C1", "quiet", False), _label("C1", "bakery", True)], overwrite=False)
    facts = _facts(db_session, "C1")
    assert facts["quiet"] == (True, "known", "직접 조사")     # 정예 값 유지
    assert facts["bakery"][0] is True                          # 인허가 전용 라벨은 추가
    assert (result.upserted, result.kept) == (1, 1)


def test_curated_labels_overwrite_by_default(db_session):
    repository.upsert_places(db_session, [_row("C2", "가게", "카페")])
    repository.upsert_facts(db_session, [_label("C2", "quiet", False)], overwrite=False)
    repository.upsert_facts(db_session, [_label("C2", "quiet", True, "직접 조사")])
    assert _facts(db_session, "C2")["quiet"] == (True, "known", "직접 조사")


def test_labels_for_unknown_places_are_counted_in_both_modes(db_session):
    for overwrite in (True, False):
        result = repository.upsert_facts(db_session, [_label("NOPE", "quiet", True)], overwrite=overwrite)
        assert (result.upserted, result.place_not_found) == (0, 1)


# ---- 명령 수준(load.py) ----

def _write_cafe_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["관리번호", "사업장명", "업태", "도로명주소", "위도", "경도", "전화번호"])
        w.writeheader()
        w.writerows(rows)


def test_load_cafes_authoritative_flag_overwrites_and_reports(db_session, tmp_path):
    repository.upsert_places(db_session, [_row("D1", "커버리지 이름", "음식점", source="permit")])
    csv_path = tmp_path / "cafes.csv"
    _write_cafe_csv(csv_path, [{"관리번호": "D1", "사업장명": "정예 카페", "업태": "커피숍", "도로명주소": "서울특별시 성동구 성수이로 1",
                                "위도": "37.5445", "경도": "127.0561", "전화번호": ""}])
    lines = load.load_cafes(db_session, csv_path, labels=None, constraints=CONSTRAINTS, authoritative=True)
    place = _place(db_session, "D1")
    assert (place.name, place.category) == ("정예 카페", "카페")
    assert any("이름 바뀜 1, 분류 바뀜 1" in l for l in lines)


def test_load_cafes_without_flag_keeps_old_behavior(db_session, tmp_path):
    repository.upsert_places(db_session, [_row("D2", "커버리지 이름", "음식점")])
    csv_path = tmp_path / "cafes.csv"
    _write_cafe_csv(csv_path, [{"관리번호": "D2", "사업장명": "정예 카페", "업태": "커피숍", "도로명주소": "서울특별시 성동구 성수이로 1",
                                "위도": "37.5445", "경도": "127.0561", "전화번호": ""}])
    lines = load.load_cafes(db_session, csv_path, labels=None, constraints=CONSTRAINTS)
    assert _place(db_session, "D2").category == "음식점"
    assert any("다른 분류로 이미 있음 1행" in l for l in lines)

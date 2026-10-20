"""적재 옵션 — --all-regions 전달, --close-missing(안전장치·dry-run·되살리기). 실제 PostgreSQL+PostGIS."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from places import ingest, load, repository
from places.models import Place, PlaceFact

HEADER = "관리번호,사업장명,영업상태명,상세영업상태명,업태구분명,도로명전체주소,소재지전체주소,소재지전화,좌표정보(X),좌표정보(Y)\n"
BUSAN = {"address": "부산광역시 중구 1", "x": "129.0756", "y": "35.1796"}


def _line(source_id, status="영업/정상", address="서울특별시 성동구 아차산로 1", x="127.0561", y="37.5445"):
    return f"{source_id},가게{source_id},{status},,한식,{address},{address},,{x},{y}\n"


def _write(tmp_path, name, *lines):
    path = tmp_path / name
    path.write_text(HEADER + "".join(lines), encoding="utf-8")
    return path


def _place(db, source_id, source="permit"):
    return db.execute(select(Place).where(Place.source == source, Place.source_id == source_id)).scalar_one()


def _seed(db, ids, *, curated=(), source="permit"):
    repository.upsert_places(db, [ingest.PlaceRow(source, i, f"가게{i}", "음식점", "서울특별시 성동구 1", None, 37.5445, 127.0561, "open") for i in ids])
    for i in curated:
        _place(db, i, source).curated = True
    db.flush()


def _load(db, files, **kw):
    return load.load_permit(db, files, crs="EPSG:4326", encoding=None, **kw)


def _main(db, argv):
    db.close = lambda: None   # type: ignore[method-assign] — main이 세션을 닫지 않게 한다(테스트 세션 재사용)
    return load.main(argv, session_factory=lambda: db)


# ---- --all-regions ----

def test_permit_all_regions_loads_other_regions_and_reports_distribution(db_session, tmp_path):
    f = _write(tmp_path, "a.csv", _line("S1"), _line("B1", **{"address": BUSAN["address"], "x": BUSAN["x"], "y": BUSAN["y"]}))
    lines = _load(db_session, f, seoul_only=False)
    assert _place(db_session, "B1").status == "open"
    assert any("지역별" in line and "부산 1" in line and "서울 1" in line for line in lines)


def test_permit_default_is_still_seoul_only(db_session, tmp_path):
    f = _write(tmp_path, "a.csv", _line("S1"), _line("B1", **BUSAN))
    _load(db_session, f)
    assert db_session.scalar(select(func.count()).select_from(Place).where(Place.source_id == "B1")) == 0


def test_cli_all_regions_flag_reaches_the_loader(db_session, tmp_path):
    f = _write(tmp_path, "a.csv", _line("B1", **BUSAN))
    assert _main(db_session, ["permit", "--file", str(f), "--crs", "EPSG:4326", "--all-regions"]) == 0
    assert _place(db_session, "B1").status == "open"


def test_cli_all_regions_for_tourapi_cafes_and_restaurants(db_session, tmp_path, capsys):
    t = tmp_path / "t.json"
    t.write_text('[{"contentid":"B1","contenttypeid":"28","title":"부산 레포츠","addr1":"부산광역시 중구 1","mapx":"129.07","mapy":"35.17","areacode":"6"}]', encoding="utf-8")
    assert _main(db_session, ["tourapi", "--file", str(t), "--all-regions"]) == 0
    assert _place(db_session, "B1", "tourapi").category == "관광지"   # 레포츠(28)·타 지역
    csv_path = tmp_path / "c.csv"
    csv_path.write_text("관리번호,사업장명,업태,도로명주소,위도,경도\nBC1,부산 카페,커피숍,부산광역시 중구 1,35.17,129.07\n", encoding="utf-8")
    assert _main(db_session, ["cafes", "--file", str(csv_path)]) == 0
    assert db_session.scalar(select(func.count()).select_from(Place).where(Place.source_id == "BC1")) == 0
    assert _main(db_session, ["cafes", "--file", str(csv_path), "--all-regions"]) == 0
    assert _place(db_session, "BC1").category == "카페"
    rest = tmp_path / "r.csv"
    rest.write_text("관리번호,사업장명,업태,도로명주소,위도,경도\nBR1,부산 식당,한식,부산광역시 중구 1,35.17,129.07\n", encoding="utf-8")
    assert _main(db_session, ["restaurants", "--file", str(rest), "--all-regions"]) == 0
    assert _place(db_session, "BR1").category == "음식점"


# ---- 레포츠(28) ----

def test_tourapi_leisure_is_loaded_as_tourist_spot(db_session, tmp_path):
    f = tmp_path / "t.json"
    f.write_text('[{"contentid":"L1","contenttypeid":"28","title":"한강 레포츠","addr1":"서울특별시 영등포구 1","mapx":"126.93","mapy":"37.52","areacode":"1"}]', encoding="utf-8")
    load.load_tourapi(db_session, f)
    assert _place(db_session, "L1", "tourapi").category == "관광지"


# ---- --close-missing ----

def test_close_missing_closes_only_absent_non_curated_open_permit_places(db_session, tmp_path):
    _seed(db_session, ["KEEP", "GONE", "ELITE", "PAST"], curated=["ELITE"])
    _seed(db_session, ["TOUR"], source="tourapi")
    _place(db_session, "PAST").status = "closed"
    a = _write(tmp_path, "a.csv", _line("KEEP"), _line("NEW"))
    b = _write(tmp_path, "b.csv", _line("OTHER"))
    # 열린 비정예 인허가 = KEEP, GONE 중 파일에 나온 것 1곳(50%) → 통과
    lines = _load(db_session, [a, b], close_missing=True)
    assert any("파일에 없어 닫음 1행" in line for line in lines)
    status = {i: _place(db_session, i).status for i in ("KEEP", "GONE", "ELITE", "PAST", "NEW")}
    assert status == {"KEEP": "open", "GONE": "closed", "ELITE": "open", "PAST": "closed", "NEW": "open"}
    assert _place(db_session, "TOUR", "tourapi").status == "open"


def test_close_missing_keeps_labels(db_session, tmp_path):
    _seed(db_session, ["KEEP", "GONE"])
    repository.upsert_facts(db_session, [ingest.LabelRow("permit", "GONE", "vegan_available", True, "known", 3, None, "근거", "x")])
    pid = _place(db_session, "GONE").id
    before = db_session.scalar(select(func.count()).select_from(PlaceFact).where(PlaceFact.place_id == pid))
    assert before == 1
    _load(db_session, [_write(tmp_path, "a.csv", _line("KEEP")), _write(tmp_path, "b.csv", _line("OTHER"))], close_missing=True)
    assert _place(db_session, "GONE").status == "closed"
    assert db_session.scalar(select(func.count()).select_from(PlaceFact).where(PlaceFact.place_id == pid)) == 1


def test_close_missing_is_off_by_default(db_session, tmp_path):
    _seed(db_session, ["KEEP", "GONE"])
    _load(db_session, [_write(tmp_path, "a.csv", _line("KEEP")), _write(tmp_path, "b.csv", _line("X"))])
    assert _place(db_session, "GONE").status == "open"


def test_close_missing_refuses_a_single_file(db_session, tmp_path):
    _seed(db_session, ["KEEP", "GONE"])
    with pytest.raises(load.CloseMissingRefused):
        _load(db_session, _write(tmp_path, "a.csv", _line("KEEP")), close_missing=True)
    assert _place(db_session, "GONE").status == "open"


def test_close_missing_refuses_under_30_percent_and_force_bypasses(db_session, tmp_path):
    _seed(db_session, [f"P{i}" for i in range(10)])
    a, b = _write(tmp_path, "a.csv", _line("P0"), _line("P1")), _write(tmp_path, "b.csv", _line("Z"))
    with pytest.raises(load.CloseMissingRefused):
        _load(db_session, [a, b], close_missing=True)
    assert db_session.scalar(select(func.count()).select_from(Place).where(Place.status == "closed")) == 0
    assert db_session.scalar(select(func.count()).select_from(Place).where(Place.source_id == "Z")) == 0   # 거부면 신규도 넣지 않았다
    lines = _load(db_session, [a, b], close_missing=True, force=True)
    assert any("파일에 없어 닫음 8행" in line for line in lines)


def test_places_in_the_file_but_skipped_are_not_closed(db_session, tmp_path):
    _seed(db_session, ["NOXY", "KEEP"])
    a = _write(tmp_path, "a.csv", _line("NOXY", x="", y=""), _line("KEEP"))
    _load(db_session, [a, _write(tmp_path, "b.csv", _line("Z"))], close_missing=True)
    assert _place(db_session, "NOXY").status == "open"


def test_close_missing_dry_run_reports_count_and_leaves_db_untouched(db_session, tmp_path, capsys):
    _seed(db_session, ["KEEP", "GONE"])
    db_session.commit()   # main의 롤백이 시드를 지우지 않게(세이브포인트 해제)
    a, b = _write(tmp_path, "a.csv", _line("KEEP")), _write(tmp_path, "b.csv", _line("X"))
    code = _main(db_session, ["permit", "--file", str(a), "--file", str(b), "--crs", "EPSG:4326", "--close-missing", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0 and "파일에 없어 닫음 1행" in out and "dry-run" in out
    db_session.expire_all()
    assert _place(db_session, "GONE").status == "open"


def test_cli_refuses_a_single_file_with_exit_2(db_session, tmp_path, capsys):
    _seed(db_session, ["GONE"])
    db_session.commit()
    a = _write(tmp_path, "a.csv", _line("X"))
    code = _main(db_session, ["permit", "--file", str(a), "--crs", "EPSG:4326", "--close-missing"])
    assert code == 2 and "거부" in capsys.readouterr().err
    assert _place(db_session, "GONE").status == "open"


def test_directory_and_glob_expand_to_all_files(tmp_path):
    _write(tmp_path, "a.csv", _line("A"))
    _write(tmp_path, "b.csv", _line("B"))
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    assert [p.name for p in load.expand_files([tmp_path])] == ["a.csv", "b.csv"]
    assert [p.name for p in load.expand_files([tmp_path / "*.csv", tmp_path / "a.csv"])] == ["a.csv", "b.csv"]
    with pytest.raises(FileNotFoundError):
        load.expand_files([tmp_path / "none*.csv"])


def test_closed_place_comes_back_when_the_file_lists_it_open_again(db_session, tmp_path):
    _seed(db_session, ["KEEP", "GONE"])
    _load(db_session, [_write(tmp_path, "a.csv", _line("KEEP")), _write(tmp_path, "b.csv", _line("X"))], close_missing=True)
    assert _place(db_session, "GONE").status == "closed"
    name_before = _place(db_session, "GONE").name
    lines = _load(db_session, [_write(tmp_path, "c.csv", _line("GONE", x="127.5", y="37.9"))])
    place = _place(db_session, "GONE")
    assert place.status == "open" and place.name == name_before   # 이름·좌표는 그대로, status만
    assert any("되살림" in line for line in lines)

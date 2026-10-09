"""자체 장소 DB — 적재(upsert, 멱등, 폐업 갱신)와 6개 공개 함수의 실제 구현. 실제 PostgreSQL+PostGIS."""

import csv
import json
import uuid
from pathlib import Path

import pytest
from geoalchemy2 import Geography
from sqlalchemy import func, select

from places import api, ingest, load, repository
from places.models import Place, PlaceFact
from places.schemas import Area, PlaceHint

FIX = Path(__file__).parent / "fixtures"
CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"


@pytest.fixture()
def loaded(db_session):
    load.load_permit(db_session, FIX / "permit_sample.csv", crs="EPSG:5174", encoding=None)
    load.load_tourapi(db_session, FIX / "tourapi_items.json")
    load.load_labels(db_session, FIX / "labels.csv", constraints=CONSTRAINTS, encoding=None)
    return db_session


def _pid(db, source, source_id):
    return str(db.execute(select(Place.id).where(Place.source == source, Place.source_id == source_id)).scalar_one())


def _hint(name, lat, lng, category="음식점", kakao_place_id="k1"):
    return PlaceHint(kakao_place_id=kakao_place_id, name=name, lat=lat, lng=lng, category=category)


# ---- 적재 ----

def test_load_counts_and_what_was_left_out(loaded):
    db = loaded
    assert db.scalar(select(func.count()).select_from(Place).where(Place.source == "permit")) == 13   # 영업 12곳 + 관리번호가 같은 두 줄(P048)은 한 곳. 폐업 3은 새로 안 넣는다
    assert db.scalar(select(func.count()).select_from(Place).where(Place.source == "tourapi")) == 3
    assert db.scalar(select(func.count()).select_from(Place).where(Place.status == "closed")) == 0
    assert db.scalar(select(Place.id).where(Place.source_id.in_(["T200", "T300", "P040", "P042"]))) is None   # 숙박·음식점(Tour)·좌표 없음·경기


def test_stored_coordinates_are_converted_wgs84(loaded):
    info = api.get_places([_pid(loaded, "permit", "P001")], db=loaded)
    p = next(iter(info.values()))
    assert (p.lat, p.lng) == pytest.approx((37.5445, 127.0561), abs=1e-5)
    assert p.name == "성수 칼국수" and p.category == "음식점"


def test_load_is_idempotent(loaded):
    before = loaded.scalar(select(func.count()).select_from(Place))
    facts_before = loaded.scalar(select(func.count()).select_from(PlaceFact))
    load.load_permit(loaded, FIX / "permit_sample.csv", crs="EPSG:5174", encoding=None)
    load.load_tourapi(loaded, FIX / "tourapi_items.json")
    load.load_labels(loaded, FIX / "labels.csv", constraints=CONSTRAINTS, encoding=None)
    assert loaded.scalar(select(func.count()).select_from(Place)) == before
    assert loaded.scalar(select(func.count()).select_from(PlaceFact)) == facts_before


def test_reload_keeps_kakao_match_and_ids(loaded):
    pid = _pid(loaded, "permit", "P001")
    api.record_kakao_match(pid, "k-1", "http://place.map.kakao.com/1", db=loaded)
    load.load_permit(loaded, FIX / "permit_sample.csv", crs="EPSG:5174", encoding=None)
    assert _pid(loaded, "permit", "P001") == pid
    assert api.get_places([pid], db=loaded)[pid].kakao_place_url == "http://place.map.kakao.com/1"


def test_existing_place_that_turns_closed_is_marked_and_leaves_search(loaded):
    pid = _pid(loaded, "permit", "P001")
    rows = [ingest.PlaceRow("permit", "P001", "성수 칼국수", "음식점", None, None, 37.5445, 127.0561, "closed")]
    result = repository.upsert_places(loaded, rows)
    assert result.closed_marked == 1 and result.closed_ignored == 0
    assert loaded.get(Place, uuid.UUID(pid)).status == "closed"
    assert pid not in {r.place_id for r in api.search_nearby_own("음식점", [Area(37.5445, 127.0561, 500)], db=loaded)}
    assert api.match_place(_hint("성수 칼국수", 37.5445, 127.0561), db=loaded) is None
    assert api.get_places([pid], db=loaded)[pid].name == "성수 칼국수"   # 이미 핀이 가리키는 장소는 계속 조회된다


def test_new_closed_place_is_not_inserted(db_session):
    rows = [ingest.PlaceRow("permit", "Z1", "처음부터 폐업", "음식점", None, None, 37.5, 127.0, "closed")]
    result = repository.upsert_places(db_session, rows)
    assert (result.inserted, result.closed_ignored) == (0, 1)
    assert db_session.scalar(select(func.count()).select_from(Place)) == 0


def test_reopened_place_comes_back(loaded):
    pid = _pid(loaded, "permit", "P001")
    repository.upsert_places(loaded, [ingest.PlaceRow("permit", "P001", "성수 칼국수", "음식점", None, None, 37.5445, 127.0561, "closed")])
    repository.upsert_places(loaded, [ingest.PlaceRow("permit", "P001", "성수 칼국수", "음식점", None, None, 37.5445, 127.0561, "open")])
    assert loaded.get(Place, uuid.UUID(pid)).status == "open"


# ---- match_place ----

def test_match_place_finds_the_own_db_place_and_returns_its_values(loaded):
    m = api.match_place(_hint("성수칼국수 (본점)", 37.5447, 127.0563), db=loaded)
    assert m.place_id == _pid(loaded, "permit", "P001")
    assert (m.name, m.category) == ("성수 칼국수", "음식점")
    assert (m.lat, m.lng) == pytest.approx((37.5445, 127.0561), abs=1e-5)   # 힌트가 아니라 자체 DB 좌표


def test_match_place_none_cases(loaded):
    assert api.match_place(_hint("성수 칼국수", 37.5445, 127.0561, category="카페"), db=loaded) is None
    assert api.match_place(_hint("성수 칼국수", 37.5445 + 0.004, 127.0561), db=loaded) is None   # 440m
    assert api.match_place(_hint("전혀 다른 이름", 37.5445, 127.0561), db=loaded) is None
    assert api.match_place(_hint("가상 호텔", 37.56, 126.98, category="숙소"), db=loaded) is None
    assert api.match_place(_hint("뭐든", 37.56, 126.98, category="기타"), db=loaded) is None


def test_match_place_tourist_spot(loaded):
    m = api.match_place(_hint("서울숲", 37.5440, 127.0370, category="관광지"), db=loaded)
    assert m.place_id == _pid(loaded, "tourapi", "T100")


def test_match_place_via_recorded_kakao_id_survives_name_difference(loaded):
    pid = _pid(loaded, "permit", "P001")
    api.record_kakao_match(pid, "k-77", "http://u", db=loaded)
    assert api.match_place(_hint("다르게 적힌 이름", 37.5445, 127.0561, kakao_place_id="k-77"), db=loaded).place_id == pid


def test_match_place_respects_candidate_cap(loaded, monkeypatch):
    seen = {}
    real = repository.find_candidates

    def spy(db, *a, **k):
        seen["n"] = len(real(db, *a, **k))
        return real(db, *a, **k)

    monkeypatch.setattr(repository, "find_candidates", spy)
    api.match_place(_hint("성수 칼국수", 37.5445, 127.0561), db=loaded)
    assert 1 <= seen["n"] <= 20


def test_ambiguous_same_name_nearby_is_none(db_session):
    repository.upsert_places(db_session, [
        ingest.PlaceRow("permit", "A", "똑같은 카페", "카페", None, None, 37.50000, 127.00000, "open"),
        ingest.PlaceRow("permit", "B", "똑같은 카페", "카페", None, None, 37.50010, 127.00000, "open"),
    ])
    assert api.match_place(_hint("똑같은 카페", 37.50000, 127.00000, "카페"), db=db_session) is None


# ---- 반경 판정은 DB(ST_DWithin) 한 곳 — 300m 경계 (#316) ----

ORIGIN = (37.5, 127.0)


def _place_at(db, source_id, distance, azimuth, *, name="경계 카페", category="카페", kakao_place_id=None):
    """ORIGIN에서 타원체 기준 distance(m)만큼 azimuth(도) 방향에 장소를 둔다 — DB가 재는 거리와 정확히 일치한다."""
    point = func.ST_Project(func.ST_SetSRID(func.ST_MakePoint(ORIGIN[1], ORIGIN[0]), 4326).cast(Geography()), distance, func.radians(azimuth))
    db.add(Place(source="permit", source_id=source_id, name=name, category=category, geom=point, status="open",
                 kakao_place_id=kakao_place_id))
    db.flush()


@pytest.mark.parametrize("azimuth", [0, 90, 45])   # 북·동·북동 — 구(haversine)와 타원체의 차이가 방향마다 다르다
def test_radius_boundary_is_decided_by_the_db_alone(db_session, azimuth):
    """타원체로 299.9m는 안, 300.1m는 밖. 북쪽에서는 haversine이 299.9m 지점을 300.4m로 재서 예전엔 안쪽도 거절했다."""
    _place_at(db_session, "in", 299.9, azimuth, name="안쪽 카페")
    _place_at(db_session, "out", 300.1, azimuth, name="바깥 카페")

    inside = _hint("안쪽 카페", *ORIGIN, "카페")
    outside = _hint("바깥 카페", *ORIGIN, "카페")

    assert api.match_place(inside, db=db_session) is not None
    assert api.match_place(outside, db=db_session) is None
    assert api.pinnable_flags([inside, outside], db=db_session) == [True, False]   # 검색(pinnable)과 핀 생성이 같은 답


def test_find_candidates_many_returns_the_same_set_as_find_candidates(db_session):
    for i in range(25):
        _place_at(db_session, f"n{i}", 10 + i * 10, (i * 37) % 360, name=f"카페{i}")   # 10m~250m, 25곳
    _place_at(db_session, "edge-in", 299.9, 0, name="안 카페")
    _place_at(db_session, "edge-out", 300.1, 0, name="밖 카페")
    _place_at(db_session, "other-cat", 20, 0, name="식당", category="음식점")
    _place_at(db_session, "far-linked", 5000, 0, name="멀리 있는 연결 장소", kakao_place_id="k-far")
    hints = [_hint("x", *ORIGIN, "카페", kakao_place_id=None), _hint("x", *ORIGIN, "카페", kakao_place_id="k-far"),
             _hint("x", ORIGIN[0] + 0.01, ORIGIN[1], "카페", kakao_place_id=None), _hint("x", *ORIGIN, "음식점", kakao_place_id=None)]

    many = repository.find_candidates_many(db_session, hints)

    for h, got in zip(hints, many):
        one = repository.find_candidates(db_session, h.lat, h.lng, h.category, h.kakao_place_id)
        assert [c.place_id for c in got] == [c.place_id for c in one]   # 순서(가까운 순)까지 같다
    assert len(many[0]) == 20                                           # 힌트별 상한 — 반경 안 장소는 26곳이다
    assert [c.name for c in many[0]][:2] == ["카페0", "카페1"]
    assert "밖 카페" not in {c.name for c in many[0]}
    assert [c.name for c in many[1]][-1] == "멀리 있는 연결 장소"       # 카카오 ID로 연결된 장소는 반경 밖이어도 붙는다
    assert many[2] == []                                                # 1.1km 떨어진 힌트
    assert [c.name for c in many[3]] == ["식당"]


def test_candidates_carry_the_db_distance_and_kakao_only_ones_have_none(db_session):
    """pick_match가 파이썬으로 거리를 다시 재지 않도록 두 조회 모두 ST_Distance를 Candidate에 싣는다(#381)."""
    _place_at(db_session, "near", 40, 90, name="가까운 카페")
    _place_at(db_session, "far-linked", 5000, 0, name="멀리 연결된 카페", kakao_place_id="k-far")
    hint = _hint("x", *ORIGIN, "카페", kakao_place_id="k-far")

    one = repository.find_candidates(db_session, hint.lat, hint.lng, hint.category, hint.kakao_place_id)
    many = repository.find_candidates_many(db_session, [hint])[0]

    for got in (one, many):
        by_name = {c.name: c for c in got}
        assert by_name["가까운 카페"].distance_m == pytest.approx(40, abs=0.01)   # 타원체 기준 — ST_Project와 같은 잣대
        assert by_name["멀리 연결된 카페"].distance_m is None


def test_same_name_pick_uses_db_distance_end_to_end(db_session):
    _place_at(db_session, "a", 200, 0, name="같은 이름 카페")
    _place_at(db_session, "b", 20, 90, name="같은 이름 카페")
    m = api.match_place(_hint("같은 이름 카페", *ORIGIN, "카페"), db=db_session)
    assert m is not None and (m.lat, m.lng) != (0, 0)
    assert round(m.lng, 4) != round(ORIGIN[1], 4) and abs(m.lat - ORIGIN[0]) < 0.0001   # 동쪽 20m 쪽이 골라진다


def test_find_candidates_many_is_one_query_with_bounded_rows(db_session):
    from sqlalchemy import event

    for i in range(30):
        _place_at(db_session, f"n{i}", 10 + i * 5, 0, name=f"카페{i}")
    hints = [_hint("x", *ORIGIN, "카페", kakao_place_id=None)] * 3 + [_hint("y", ORIGIN[0] + 0.0005, ORIGIN[1], "카페", kakao_place_id=None)]
    sizes: list[int] = []
    engine = db_session.get_bind()
    listener = lambda conn, cur, stmt, *a: sizes.append(1) if stmt.lstrip().upper().startswith("SELECT") else None
    event.listen(engine, "before_cursor_execute", listener)
    try:
        out = repository.find_candidates_many(db_session, hints)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(sizes) == 1
    assert [len(c) for c in out] == [20, 20, 20, 20]


# ---- pinnable_flags / record_kakao_match ----

def test_pinnable_flags_do_not_write(loaded):
    pid = _pid(loaded, "permit", "P001")
    flags = api.pinnable_flags([_hint("성수 칼국수", 37.5445, 127.0561), _hint("없는 가게", 37.5445, 127.0561)], db=loaded)
    assert flags == [True, False]
    assert loaded.get(Place, uuid.UUID(pid)).kakao_place_id is None
    assert loaded.get(Place, uuid.UUID(pid)).kakao_matched_at is None


def test_pinnable_flags_is_one_query_for_many_hints(loaded):
    from sqlalchemy import event

    hints = [_hint("성수 칼국수", 37.5445, 127.0561), _hint("없는 가게", 37.5445, 127.0561)] * 8   # 16개
    selects: list[str] = []
    engine = loaded.get_bind()
    listener = lambda conn, cur, stmt, *a: selects.append(stmt) if stmt.lstrip().upper().startswith("SELECT") else None
    event.listen(engine, "before_cursor_execute", listener)
    try:
        flags = api.pinnable_flags(hints, db=loaded)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert flags == [True, False] * 8
    assert len(selects) == 1


def test_pinnable_flags_equal_match_place_per_hint(loaded):
    hints = [_hint("성수 칼국수", 37.5445, 127.0561), _hint("성수 칼국수", 37.60, 127.10),
             _hint("성수 칼국수", 37.5445, 127.0561, category="숙소"), _hint("성수 칼국수", 37.5445, 127.0561, category="카페")]
    assert api.pinnable_flags(hints, db=loaded) == [api.match_place(h, db=loaded) is not None for h in hints]


def test_pinnable_flags_empty_and_non_own_category_skip_the_db(loaded):
    assert api.pinnable_flags([], db=loaded) == []
    assert api.pinnable_flags([_hint("x", 37.5, 127.0, category="숙소")], db=loaded) == [False]


def test_record_kakao_match_writes_only_id_url_and_date(loaded):
    pid = _pid(loaded, "permit", "P001")
    api.record_kakao_match(pid, "k1", "http://p/1", db=loaded)
    row = loaded.get(Place, uuid.UUID(pid))
    loaded.refresh(row)
    assert (row.kakao_place_id, row.kakao_place_url) == ("k1", "http://p/1") and row.kakao_matched_at is not None
    assert row.name == "성수 칼국수"   # 카카오 값으로 이름·주소·좌표를 바꾸지 않는다


def test_record_kakao_match_keeps_the_first_id_and_url(loaded):
    """#248 — 같은 자체 장소를 다른 카카오 ID로 찍어도 먼저 기록된 ID·URL은 그대로다(다른 지도의 링크가 안 바뀐다)."""
    pid = _pid(loaded, "permit", "P001")
    api.record_kakao_match(pid, "k1", "http://p/1", db=loaded)
    api.record_kakao_match(pid, "k2", "http://p/2", db=loaded)
    row = loaded.get(Place, uuid.UUID(pid))
    loaded.refresh(row)
    assert (row.kakao_place_id, row.kakao_place_url) == ("k1", "http://p/1")


def test_record_kakao_match_same_id_refreshes_the_date_only(loaded):
    pid = _pid(loaded, "permit", "P001")
    api.record_kakao_match(pid, "k1", "http://p/1", db=loaded)
    row = loaded.get(Place, uuid.UUID(pid))
    loaded.refresh(row)
    row.kakao_matched_at = func.now() - func.make_interval(0, 0, 0, 1)   # 하루 전으로
    loaded.flush()
    loaded.refresh(row)
    old = row.kakao_matched_at
    api.record_kakao_match(pid, "k1", "http://p/1", db=loaded)
    loaded.refresh(row)
    assert row.kakao_matched_at > old and row.kakao_place_url == "http://p/1"


def test_record_kakao_match_unknown_place_raises(loaded):
    with pytest.raises(KeyError):
        api.record_kakao_match(str(uuid.uuid4()), "k", "u", db=loaded)


# ---- get_places ----

def test_get_places_is_batched_and_drops_unknown_or_malformed_ids(loaded):
    a, b = _pid(loaded, "permit", "P001"), _pid(loaded, "tourapi", "T101")
    got = api.get_places([a, str(uuid.uuid4()), "not-a-uuid", b], db=loaded)
    assert set(got) == {a, b} and got[b].name == "경복궁" and got[b].category == "관광지"


def test_get_places_uses_one_query_for_many_ids(loaded, test_engine):
    from sqlalchemy import event

    ids = [_pid(loaded, "permit", i) for i in ("P001", "P002", "P003", "P004", "P005")]
    count = {"n": 0}
    bind = loaded.get_bind()
    event.listen(bind, "before_cursor_execute", lambda *a, **k: count.__setitem__("n", count["n"] + 1))
    api.get_places(ids, db=loaded)
    assert count["n"] == 1   # N+1 금지


# ---- search_nearby_own ----

def test_search_nearby_own_radius_category_and_status(loaded):
    near = api.search_nearby_own("음식점", [Area(37.5445, 127.0561, 300)], db=loaded)
    assert {r.place_id for r in near} == {_pid(loaded, "permit", "P001"), _pid(loaded, "permit", "P002")}
    assert api.search_nearby_own("카페", [Area(37.5445, 127.0561, 300)], db=loaded)[0].place_id == _pid(loaded, "permit", "P010")
    assert [r.place_id for r in api.search_nearby_own("음식점", [Area(37.5445, 127.0561, 10)], db=loaded)] == [_pid(loaded, "permit", "P001")]
    assert api.search_nearby_own("숙소", [Area(37.5445, 127.0561, 5000)], db=loaded) == []
    assert api.search_nearby_own("기타", [Area(37.5445, 127.0561, 5000)], db=loaded) == []


def test_search_nearby_own_union_of_areas_and_empty_areas(loaded):
    refs = api.search_nearby_own("관광지", [Area(37.5444, 127.0374, 200), Area(37.5796, 126.9770, 200)], db=loaded)
    assert {r.place_id for r in refs} == {_pid(loaded, "tourapi", "T100"), _pid(loaded, "tourapi", "T101")}
    assert api.search_nearby_own("관광지", [], db=loaded) == []


def test_search_nearby_own_returns_coordinates(loaded):
    [ref] = api.search_nearby_own("관광지", [Area(37.5512, 126.9882, 100)], db=loaded)
    assert (ref.lat, ref.lng) == pytest.approx((37.5512, 126.9882), abs=1e-5)


# ---- get_facts ----

def test_get_facts_returns_labels_as_stored_including_unknown(loaded):
    pid = _pid(loaded, "permit", "P001")
    by_key = {f.fact_key: f for f in api.get_facts([pid], db=loaded)[pid]}
    assert by_key["contains_shellfish"].value is True and by_key["contains_shellfish"].confidence == "known"
    assert "price_bucket" not in by_key   # #423에서 뺀 키라 적재하지 않는다
    assert by_key["oily_focused"].confidence == "unknown" and by_key["oily_focused"].value is None
    assert by_key["spicy_focused"].value is True   # 같은 키가 둘이면 마지막 줄


def test_unknown_label_value_is_sql_null_not_json_null(loaded):
    pid = uuid.UUID(_pid(loaded, "permit", "P001"))
    is_sql_null = loaded.execute(
        select(PlaceFact.value.is_(None)).where(PlaceFact.place_id == pid, PlaceFact.fact_key == "oily_focused")
    ).scalar_one()
    assert is_sql_null is True


def test_get_facts_without_labels_is_empty_list_for_every_requested_id(loaded):
    pid, other = _pid(loaded, "permit", "P004"), str(uuid.uuid4())
    assert api.get_facts([pid, other, "garbage"], db=loaded) == {pid: [], other: [], "garbage": []}


def test_labels_for_missing_places_and_bad_rows_are_not_loaded(loaded):
    assert loaded.scalar(select(func.count()).select_from(PlaceFact)) == 8   # 파일 17줄 → 해석 가능 9(중복 1 합침 포함) → 장소 없는 NOPE 1줄 제외
    pid = uuid.UUID(_pid(loaded, "permit", "P001"))
    keys = set(loaded.scalars(select(PlaceFact.fact_key).where(PlaceFact.place_id == pid)))
    assert "made_up_key" not in keys and "is_open" not in keys


def test_relabel_overwrites_and_keeps_one_row(loaded):
    pid = uuid.UUID(_pid(loaded, "permit", "P001"))
    row = ingest.LabelRow("permit", "P001", "contains_shellfish", False, "known", 3, None)
    repository.upsert_facts(loaded, [row])
    values = loaded.scalars(select(PlaceFact.value).where(PlaceFact.place_id == pid, PlaceFact.fact_key == "contains_shellfish")).all()
    assert values == [False]


def test_facts_cascade_when_place_is_deleted(loaded):
    pid = uuid.UUID(_pid(loaded, "permit", "P001"))
    loaded.delete(loaded.get(Place, pid))
    loaded.flush()
    assert loaded.scalar(select(func.count()).select_from(PlaceFact).where(PlaceFact.place_id == pid)) == 0


# ---- CLI ----

def test_cli_dry_run_writes_nothing(db_session, capsys):
    rc = load.main(["permit", "--file", str(FIX / "permit_sample.csv"), "--dry-run"], session_factory=lambda: _NoCloseSession(db_session))
    out = capsys.readouterr().out
    assert rc == 0 and "dry-run" in out and "읽음 25행" in out
    assert db_session.scalar(select(func.count()).select_from(Place)) == 0


def test_cli_reports_skip_reasons(db_session, capsys):
    load.main(["labels", "--file", str(FIX / "labels.csv"), "--dry-run"], session_factory=lambda: _NoCloseSession(db_session))
    out = capsys.readouterr().out
    assert "모르는 fact_key: made_up_key" in out and "모르는 fact_key: price_bucket" in out


def test_cli_tourapi_loads_types_12_14_38_with_labels(db_session, tmp_path, capsys):
    items = [
        {"contentid": "1", "contenttypeid": "12", "title": "경복궁", "addr1": "서울특별시 종로구 사직로 161", "mapx": "126.977", "mapy": "37.5796"},
        {"contentid": "2", "contenttypeid": "14", "title": "국립중앙박물관", "addr1": "서울특별시 용산구 서빙고로 137", "mapx": "126.9804", "mapy": "37.5239"},
        {"contentid": "3", "contenttypeid": "38", "title": "광장시장", "addr1": "서울특별시 종로구 창경궁로 88", "mapx": "126.9996", "mapy": "37.5700"},
        {"contentid": "4", "contenttypeid": "32", "title": "호텔", "addr1": "서울특별시 중구 소공로 1", "mapx": "126.98", "mapy": "37.56"},
        {"contentid": "5", "contenttypeid": "12", "title": "좌표 잘못", "addr1": "서울특별시 관악구 관악로 173", "mapx": "127.709322", "mapy": "37.470571"},
    ]
    places_file = tmp_path / "tour.json"
    places_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    labels_file = tmp_path / "labels.csv"
    header = next(csv.reader((FIX / "labels.csv").open(encoding="utf-8-sig")))
    labels_file.write_text(",".join(header) + "\n", encoding="utf-8")
    rc = load.main(["tourapi", "--file", str(places_file), "--labels", str(labels_file)], session_factory=lambda: _NoCloseSession(db_session))
    out = capsys.readouterr().out
    assert rc == 0 and "[contenttypeid 14] 받음 1 / 건너뜀 0" in out and "서울 밖 좌표: 1" in out
    rows = db_session.execute(select(Place.source_id, Place.category).where(Place.source == "tourapi").order_by(Place.source_id)).all()
    assert rows == [("1", "관광지"), ("2", "관광지"), ("3", "관광지")]


def test_cli_missing_file_exits_2(capsys):
    assert load.main(["permit", "--file", "/no/such/file.csv"]) == 2


class _NoCloseSession:
    """CLI가 close()/commit()/rollback()을 불러도 테스트 세션의 바깥 트랜잭션이 끝나지 않게 감싼다."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass

    def commit(self):
        self._s.flush()

    def rollback(self):
        self._s.rollback()


# ---- 음식점 납품본 (#207) ----

CURATED_CSV = FIX / "restaurant_curated_sample.csv"
CURATED_LABELS = FIX / "restaurant_curated_labels.json"
_MINI_KEYS = ["cuisine_korean", "cuisine_chinese", "spacious", "long_established", "franchise", "spicy_focused",
              "oily_focused", "contains_shellfish", "wait_short", "pet_friendly", "quiet"]


@pytest.fixture()
def mini_constraints(tmp_path):
    """#206 머지 전에도 신규 키로 시험할 수 있게, constraints.md 표 모양의 작은 파일을 만든다."""
    path = tmp_path / "constraints.md"
    path.write_text("| `fact_key` | 종류 |\n|---|---|\n" + "\n".join(f"| `{k}` | soft |" for k in _MINI_KEYS), encoding="utf-8")
    return path


def _restaurants(db, constraints, *, exclude_bars=False, labels=CURATED_LABELS):
    return load.load_restaurants(db, CURATED_CSV, labels=labels, constraints=constraints, exclude_bars=exclude_bars)


def test_restaurants_load_places_as_open_permit_restaurants(db_session, mini_constraints):
    _restaurants(db_session, mini_constraints)
    rows = db_session.execute(select(Place)).scalars().all()
    assert len(rows) == 9 and {p.source for p in rows} == {"permit"} and {p.category for p in rows} == {"음식점"}
    assert {p.status for p in rows} == {"open"}
    r1 = next(p for p in rows if p.source_id == "R001")
    got = api.get_places([str(r1.id)], db=db_session)[str(r1.id)]
    assert (got.lat, got.lng) == pytest.approx((37.5704, 126.9920), abs=1e-6) and got.name == "가상 한식당"


def test_restaurants_exclude_bars_drops_them_and_their_labels_are_reported_missing(db_session, mini_constraints):
    lines = _restaurants(db_session, mini_constraints, exclude_bars=True)
    assert db_session.scalar(select(func.count()).select_from(Place)) == 7
    assert db_session.scalar(select(Place.id).where(Place.source_id == "R007")) is None
    assert any("장소를 못 찾아 건너뜀 2" in l for l in lines)   # R007(제외됨) + R404


def test_restaurant_labels_store_value_confidence_evidence_and_source(db_session, mini_constraints):
    _restaurants(db_session, mini_constraints)
    pid = _pid(db_session, "permit", "R001")
    by_key = {f.fact_key: f for f in db_session.scalars(select(PlaceFact).where(PlaceFact.place_id == uuid.UUID(pid)))}
    assert by_key["spicy_focused"].value is True and by_key["spicy_focused"].confidence == "known"
    assert by_key["spicy_focused"].evidence == "가게 이름 '짬뽕'" and by_key["spicy_focused"].label_source == "menu_keyword"
    assert by_key["spicy_focused"].source_layer == 3 and "price_bucket" not in by_key   # 가격대는 #423에서 뺐다
    assert by_key["cuisine_chinese"].value is False
    for key in ("contains_shellfish", "wait_short", "pet_friendly"):
        assert by_key[key].confidence == "unknown" and by_key[key].evidence is None and by_key[key].label_source is None


def test_restaurant_unknown_label_is_sql_null_and_visible_through_get_facts(db_session, mini_constraints):
    _restaurants(db_session, mini_constraints)
    pid = _pid(db_session, "permit", "R001")
    assert db_session.execute(
        select(PlaceFact.value.is_(None)).where(PlaceFact.place_id == uuid.UUID(pid), PlaceFact.fact_key == "wait_short")
    ).scalar_one() is True
    by_key = {f.fact_key: f for f in api.get_facts([pid], db=db_session)[pid]}
    assert (by_key["wait_short"].confidence, by_key["wait_short"].value) == ("unknown", None)


def test_restaurant_load_skips_bad_label_rows_but_keeps_the_good_ones(db_session, mini_constraints):
    _restaurants(db_session, mini_constraints)
    pid = uuid.UUID(_pid(db_session, "permit", "R003"))
    keys = set(db_session.scalars(select(PlaceFact.fact_key).where(PlaceFact.place_id == pid)))
    assert keys == {"long_established"}   # made_up_key·price_bucket(#423에서 뺌)·quiet=maybe는 건너뜀


def test_restaurant_load_is_idempotent_and_reupload_replaces_evidence(db_session, mini_constraints):
    _restaurants(db_session, mini_constraints)
    places_before = db_session.scalar(select(func.count()).select_from(Place))
    facts_before = db_session.scalar(select(func.count()).select_from(PlaceFact))
    _restaurants(db_session, mini_constraints)
    assert db_session.scalar(select(func.count()).select_from(Place)) == places_before
    assert db_session.scalar(select(func.count()).select_from(PlaceFact)) == facts_before
    pid = uuid.UUID(_pid(db_session, "permit", "R001"))
    repository.upsert_facts(db_session, [ingest.LabelRow("permit", "R001", "spicy_focused", False, "known", 3, None, "새 근거", "menu_keyword")])
    row = db_session.get(PlaceFact, (pid, "spicy_focused"))
    db_session.refresh(row)
    assert (row.value, row.evidence) == (False, "새 근거")


def test_restaurant_labels_command_alone_attaches_to_already_loaded_places(db_session, mini_constraints):
    load.load_restaurants(db_session, CURATED_CSV, labels=None, constraints=mini_constraints, exclude_bars=False)
    assert db_session.scalar(select(func.count()).select_from(PlaceFact)) == 0
    lines = load._load_curated_labels(db_session, CURATED_LABELS, constraints=mini_constraints)
    assert db_session.scalar(select(func.count()).select_from(PlaceFact)) > 0 and any("place_facts upsert" in l for l in lines)


def test_restaurant_labels_with_unregistered_keys_are_reported_not_loaded(db_session, tmp_path):
    old = tmp_path / "old.md"
    old.write_text("| `fact_key` | 종류 |\n|---|---|\n| `spicy_focused` | hard |\n", encoding="utf-8")
    lines = load.load_restaurants(db_session, CURATED_CSV, labels=CURATED_LABELS, constraints=old, exclude_bars=False)
    assert any("모르는 fact_key: cuisine_korean" in l for l in lines)
    keys = set(db_session.scalars(select(PlaceFact.fact_key)))
    assert "cuisine_korean" not in keys and "spicy_focused" in keys
    assert keys <= {"spicy_focused", "contains_shellfish"}   # contains_* 재료 태그는 접두 규칙으로 항상 허용


def test_cli_restaurants_dry_run_with_labels_writes_nothing(db_session, mini_constraints, capsys):
    rc = load.main(["restaurants", "--file", str(CURATED_CSV), "--labels", str(CURATED_LABELS),
                    "--constraints", str(mini_constraints), "--dry-run"], session_factory=lambda: _NoCloseSession(db_session))
    out = capsys.readouterr().out
    assert rc == 0 and "[장소]" in out and "[라벨]" in out and "dry-run" in out and "읽음 14행" in out
    assert db_session.scalar(select(func.count()).select_from(Place)) == 0


def test_cli_restaurants_missing_labels_file_exits_2(db_session, capsys):
    assert load.main(["restaurants", "--file", str(CURATED_CSV), "--labels", "/no/such.json"],
                     session_factory=lambda: _NoCloseSession(db_session)) == 2


# ---- 카페 납품본 (#266) — 가상 카페 fixtures만 쓴다(실데이터는 저장소 밖) ----

CAFE_CSV = FIX / "cafe_curated_sample.csv"
CAFE_LABELS_JSON = FIX / "cafe_curated_labels.json"
CAFE_LABELS_CSV = FIX / "cafe_curated_labels.csv"


def _cafes(db, **kw):
    return load.load_cafes(db, CAFE_CSV, labels=kw.pop("labels", None), constraints=CONSTRAINTS, **kw)


def _fact_rows(db):
    return sorted(
        (p.source_id, f.fact_key, f.value, f.confidence, f.evidence, f.label_source)
        for f, p in db.execute(select(PlaceFact, Place).join(Place, Place.id == PlaceFact.place_id))
    )


def test_cafes_load_as_cafe_category_and_skip_unknown_types_and_missing_coordinates(db_session):
    lines = _cafes(db_session)
    rows = db_session.execute(select(Place)).scalars().all()
    assert len(rows) == 8 and {p.category for p in rows} == {"카페"} and {p.source for p in rows} == {"permit"}
    assert {p.source_id for p in rows} == {f"C00{i}" for i in range(1, 9)}
    assert any("모르는 업태: 북카페: 1" in l for l in lines) and any("좌표 없음: 1" in l for l in lines)
    near = api.search_nearby_own("카페", [Area(37.5446, 127.0562, 100)], db=db_session)
    assert len(near) == 1   # 카페 분류로 반경 검색에 잡힌다
    assert api.search_nearby_own("음식점", [Area(37.5446, 127.0562, 100)], db=db_session) == []


def test_cafes_load_is_idempotent(db_session):
    _cafes(db_session, labels=CAFE_LABELS_JSON)
    places, facts = (db_session.scalar(select(func.count()).select_from(t)) for t in (Place, PlaceFact))
    lines = _cafes(db_session, labels=CAFE_LABELS_JSON)
    assert db_session.scalar(select(func.count()).select_from(Place)) == places == 8
    assert db_session.scalar(select(func.count()).select_from(PlaceFact)) == facts
    assert any("신규 0, 갱신 8" in l for l in lines)


def test_cafe_labels_json_and_csv_paths_give_the_same_result(db_session):
    """라벨 JSON(cafe_ 접두어)을 --labels로 넣은 결과와, 기존 labels 명령(CSV)으로 넣은 결과가 같다."""
    _cafes(db_session, labels=CAFE_LABELS_JSON)
    via_json = _fact_rows(db_session)
    db_session.execute(PlaceFact.__table__.delete())
    load.load_labels(db_session, CAFE_LABELS_CSV, constraints=CONSTRAINTS, encoding=None)
    via_csv = _fact_rows(db_session)
    assert via_json == via_csv and len(via_json) == 6   # C002 price_bucket은 #423에서 뺀 키라 건너뜀
    assert next(r for r in via_json if r[:2] == ("C001", "quiet"))[2:4] == (None, "unknown")   # unknown은 값 없이 그대로 보인다


def test_cafes_command_accepts_labels_csv_too(db_session):
    lines = _cafes(db_session, labels=CAFE_LABELS_CSV)
    assert len(_fact_rows(db_session)) == 6
    assert any("장소를 못 찾아 건너뜀 1" in l for l in lines)   # C404: 장소 없는 라벨


def test_cafes_cli_dry_run_writes_nothing(db_session, capsys):
    rc = load.main(["cafes", "--file", str(CAFE_CSV), "--labels", str(CAFE_LABELS_JSON), "--dry-run"], session_factory=lambda: db_session)
    assert rc == 0 and "dry-run" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(Place)) == 0

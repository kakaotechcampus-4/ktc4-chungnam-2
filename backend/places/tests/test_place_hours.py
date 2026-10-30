"""영업시간·휴무일(#690) — is_open_on 경계, 로더 파싱, place-hours 적재(멱등·못 찾음·칸 없음), get_hours. 마지막 절만 실제 PostgreSQL."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from places import api, core, ingest, load, repository
from places.models import Place, PlaceHours

DAYS = core.WEEKDAYS


def _week(**by_day):
    """요일마다 구간 목록 — 안 준 요일은 휴무([])."""
    return {d: by_day.get(d, []) for d in DAYS}


def _m(clock):
    return core.parse_minutes(clock)


# ---- is_open_on: 순수 함수 경계 ----

@pytest.mark.parametrize("clock,expected", [
    ("10:59", "closed"), ("11:00", "open"), ("20:59", "open"), ("21:00", "closed"), ("00:00", "closed"),
])
def test_start_is_inclusive_and_end_is_exclusive(clock, expected):
    hours = _week(월=[["11:00", "21:00"]])
    assert core.is_open_on(hours, None, 0, _m(clock)) == expected


def test_empty_day_list_is_closed_even_at_noon():
    assert core.is_open_on(_week(월=[["11:00", "21:00"]]), None, 1, _m("12:00")) == "closed"


def test_always_open_is_open_the_whole_day_including_the_last_minute():
    hours = {d: [["00:00", "24:00"]] for d in DAYS}
    assert [core.is_open_on(hours, [], 3, t) for t in (0, 1, 720, 1439)] == ["open"] * 4


@pytest.mark.parametrize("clock,expected", [("16:59", "closed"), ("17:00", "open"), ("21:59", "open"), ("22:00", "closed")])
def test_break_time_with_several_spans(clock, expected):
    hours = _week(화=[["11:00", "15:00"], ["17:00", "22:00"]])
    got = core.is_open_on(hours, None, 1, _m(clock))
    assert got == expected
    assert core.is_open_on(hours, None, 1, _m("15:00")) == "closed" and core.is_open_on(hours, None, 1, _m("14:59")) == "open"


def test_past_midnight_tail_of_yesterday_counts_as_open():
    hours = _week(금=[["18:00", "26:00"]])   # 금요일 18:00 ~ 토요일 02:00
    assert core.is_open_on(hours, None, 4, _m("23:59")) == "open"
    assert core.is_open_on(hours, None, 5, _m("00:00")) == "open"    # 토요일 새벽은 어제(금) 꼬리
    assert core.is_open_on(hours, None, 5, _m("01:59")) == "open"
    assert core.is_open_on(hours, None, 5, _m("02:00")) == "closed"  # 꼬리 끝은 포함하지 않는다
    assert core.is_open_on(hours, None, 5, _m("18:00")) == "closed"  # 토요일 자체는 휴무


def test_tail_wraps_from_sunday_into_monday():
    hours = _week(일=[["20:00", "25:00"]])
    assert core.is_open_on(hours, None, 0, _m("00:59")) == "open"
    assert core.is_open_on(hours, None, 0, _m("01:00")) == "closed"


def test_yesterday_span_ending_exactly_at_24_has_no_tail():
    hours = _week(월=[["10:00", "24:00"]])
    assert core.is_open_on(hours, None, 1, _m("00:00")) == "closed"


def test_today_span_can_run_past_midnight_and_is_open_before_it():
    hours = _week(수=[["22:00", "26:00"]])
    assert core.is_open_on(hours, None, 2, _m("23:59")) == "open"


def test_closed_days_only_closed_on_listed_weekday_otherwise_unknown():
    assert core.is_open_on(None, ["월"], 0, _m("12:00")) == "closed"
    assert core.is_open_on(None, ["월"], 1, _m("12:00")) == "unknown"   # 휴무가 아니라는 것만 안다
    assert core.is_open_on(None, [], 0, _m("12:00")) == "unknown"       # 연중무휴라도 시각은 모른다


def test_nothing_known_is_unknown():
    assert core.is_open_on(None, None, 0, 0) == "unknown"
    assert core.is_open_on({}, None, 0, 0) == "unknown"


def test_hours_wins_over_closed_days_and_missing_day_key_falls_back_to_closed_days():
    hours = _week(월=[["10:00", "12:00"]])
    assert core.is_open_on(hours, ["월"], 0, _m("11:00")) == "open"
    partial = {"월": [["10:00", "12:00"]]}   # 요일 키가 빠진 값 — 빠진 요일은 hours로 모른다
    assert core.is_open_on(partial, ["화"], 1, _m("11:00")) == "closed"
    assert core.is_open_on(partial, None, 1, _m("11:00")) == "unknown"


def test_every_weekday_index_maps_to_its_own_key():
    for i in range(7):
        only = {d: [["09:00", "10:00"]] if j == i else [] for j, d in enumerate(DAYS)}
        assert [core.is_open_on(only, None, w, _m("09:30")) for w in range(7)] == ["open" if w == i else "closed" for w in range(7)]


@pytest.mark.parametrize("weekday,minutes", [(-1, 0), (7, 0), (0, -1), (0, 1440)])
def test_out_of_range_inputs_raise(weekday, minutes):
    with pytest.raises(ValueError):
        core.is_open_on(None, None, weekday, minutes)


@pytest.mark.parametrize("raw,expected", [("00:00", 0), ("09:05", 545), ("24:00", 1440), ("26:00", 1560)])
def test_parse_minutes(raw, expected):
    assert core.parse_minutes(raw) == expected


@pytest.mark.parametrize("raw", ["", "9", "9:5", "ab:cd", "10:60", "10-00"])
def test_parse_minutes_rejects_bad_text(raw):
    with pytest.raises(ValueError):
        core.parse_minutes(raw)


# ---- 로더 파싱 ----

def _entry(place_id, info=None, **extra):
    return {"place_id": place_id, "title": "가게", "info": info if info is not None else {}, **extra}


def test_label_entries_map_prefix_to_source_and_read_info_fields():
    hours = _week(월=[["11:00", "21:00"]])
    rows, report = ingest.parse_hours_entries([
        _entry("rest_R1", {"hours": hours, "closed_days": ["화", "수", "목", "금", "토", "일"]}),
        _entry("cafe_C1", {"closed_days": ["월"], "closed_note": "설 당일"}),
        _entry("tour_T1", {"hours_note": "09:00~18:00"}),
    ])
    assert [(r.source, r.source_id) for r in rows] == [("permit", "R1"), ("permit", "C1"), ("tourapi", "T1")]
    assert rows[0].hours == hours and rows[1].hours is None and rows[1].closed_note == "설 당일" and rows[2].hours_note == "09:00~18:00"
    assert (report.read, report.accepted) == (3, 3)


def test_seoul_tourist_file_uses_source_id_and_top_level_fields():
    rows, _ = ingest.parse_hours_entries([{"source_id": "3582693", "title": "x", "closed_days": [], "hours": _week(월=[["09:00", "18:00"]]), "hours_note": "n"}])
    assert (rows[0].source, rows[0].source_id, rows[0].closed_days, rows[0].hours_note) == ("tourapi", "3582693", [], "n")


def test_entries_without_any_field_make_no_row_and_are_counted():
    rows, report = ingest.parse_hours_entries([_entry("rest_R1", {"signature_menu": "x"}), _entry("rest_R2"), _entry("rest_R3", {"closed_days": None, "hours": None})])
    assert rows == [] and report.skipped["영업시간·휴무일 칸 없음(모름 — 행을 만들지 않는다)"] == 3


def test_empty_closed_days_list_is_a_value_not_missing():
    rows, _ = ingest.parse_hours_entries([_entry("rest_R1", {"closed_days": []})])
    assert rows[0].closed_days == []   # 연중무휴 — 모름이 아니다


def test_bad_ids_are_skipped_and_counted():
    rows, report = ingest.parse_hours_entries([{"place_id": "xx_1", "info": {"closed_days": []}}, {"place_id": "rest_", "info": {"closed_days": []}}, {}])
    assert rows == [] and sum(report.skipped.values()) == 3


@pytest.mark.parametrize("bad", [
    {"월": [["11:00", "21:00"]]},                                        # 요일 7개 아님
    {**_week(), "월": [["25:00", "26:00"]]},                             # 시작이 하루를 넘음
    {**_week(), "월": [["11:00", "10:00"]]},                             # 끝이 시작보다 이름
    {**_week(), "월": [["11:00", "49:00"]]},                             # 48시간 초과
    {**_week(), "월": [["11:00"]]},                                      # 구간이 두 칸 아님
    {**_week(), "월": [["아침", "저녁"]]},                               # 시각이 아님
    {**_week(), "월": "11:00-21:00"},                                    # 목록이 아님
    "월 11:00~21:00",
])
def test_malformed_hours_drop_only_that_field_and_keep_other_fields(bad):
    rows, report = ingest.parse_hours_entries([_entry("rest_R1", {"hours": bad, "closed_days": ["월"]})])
    assert rows[0].hours is None and rows[0].closed_days == ["월"]
    assert any("hours 형식" in w for w in report.warnings)


def test_malformed_only_field_leaves_no_row():
    rows, _ = ingest.parse_hours_entries([_entry("rest_R1", {"hours": {"월": 1}})])
    assert rows == []


def test_unknown_weekday_name_in_closed_days_drops_that_field():
    rows, report = ingest.parse_hours_entries([_entry("rest_R1", {"closed_days": ["월요일"], "hours_note": "n"})])
    assert rows[0].closed_days is None and rows[0].hours_note == "n" and any("closed_days 형식" in w for w in report.warnings)


def test_non_seoul_entries_need_all_regions_when_an_address_is_present():
    entries = [_entry("tour_T1", {"closed_days": []}, addr1="대전광역시 중구 1"), _entry("rest_R1", {"closed_days": []})]
    assert [r.source_id for r in ingest.parse_hours_entries(entries)[0]] == ["R1"]   # 주소 없는 항목은 판단하지 않고 통과
    rows, report = ingest.parse_hours_entries(entries, seoul_only=False)
    assert [r.source_id for r in rows] == ["T1", "R1"] and any("지역별" in line for line in report.lines())


def test_blank_notes_become_none():
    rows, _ = ingest.parse_hours_entries([_entry("rest_R1", {"closed_note": "  ", "hours_note": "", "closed_days": []})])
    assert (rows[0].closed_note, rows[0].hours_note) == (None, None)


# ---- 적재 · get_hours (실제 PostgreSQL+PostGIS) ----

def _seed(db, *keys):
    repository.upsert_places(db, [
        ingest.PlaceRow(src, sid, f"가게{sid}", "음식점" if src == "permit" else "관광지", "서울특별시 성동구 1", None, 37.5445, 127.0561, "open")
        for src, sid in keys
    ])
    db.flush()


def _pid(db, source, source_id):
    return str(db.execute(select(Place.id).where(Place.source == source, Place.source_id == source_id)).scalar_one())


def _write(tmp_path, entries, name="labels.json"):
    path = tmp_path / name
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_stores_rows_and_get_hours_returns_them(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"), ("permit", "C1"), ("tourapi", "T1"))
    hours = _week(월=[["11:00", "21:00"]], 금=[["18:00", "26:00"]])
    path = _write(tmp_path, [
        _entry("rest_R1", {"hours": hours, "closed_days": ["화", "수", "목", "토", "일"], "hours_note": "원문"}),
        _entry("cafe_C1", {"closed_days": []}),
        _entry("tour_T1", {"closed_note": "설 당일"}),
        _entry("rest_NOPE", {"closed_days": ["월"]}),
    ])
    lines = load.load_place_hours(db_session, path)
    assert any("place_hours upsert 3" in line and "장소를 못 찾아 건너뜀 1" in line for line in lines)
    ids = [_pid(db_session, "permit", "R1"), _pid(db_session, "permit", "C1"), _pid(db_session, "tourapi", "T1")]
    got = api.get_hours(ids, db=db_session)
    assert got[ids[0]].hours == hours and got[ids[0]].closed_days == ["화", "수", "목", "토", "일"] and got[ids[0]].hours_note == "원문"
    assert got[ids[1]].hours is None and got[ids[1]].closed_days == [] and got[ids[2]].closed_note == "설 당일" and got[ids[2]].closed_days is None


def test_get_hours_omits_places_without_a_row_and_bad_ids(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"), ("permit", "R2"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": []})]))
    r1, r2 = _pid(db_session, "permit", "R1"), _pid(db_session, "permit", "R2")
    assert set(api.get_hours([r1, r2, "not-a-uuid", "00000000-0000-0000-0000-000000000000"], db=db_session)) == {r1}
    assert api.get_hours([], db=db_session) == {}


def test_load_is_idempotent_and_updates_the_same_place(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["월"]})]))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["화"], "hours_note": "바뀜"})]))
    assert db_session.scalar(select(func.count()).select_from(PlaceHours)) == 1
    got = api.get_hours([_pid(db_session, "permit", "R1")], db=db_session)
    assert next(iter(got.values())).closed_days == ["화"] and next(iter(got.values())).hours_note == "바뀜"


def test_places_missing_from_the_file_keep_their_rows_and_empty_entries_do_not_erase(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"), ("permit", "R2"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["월"]}), _entry("rest_R2", {"closed_days": ["화"]})]))
    # 두 번째 파일: R1만 있고 R2는 없다. R1은 칸이 없는 항목으로도 한 번 더 온다 — 기존 행을 지우지 않는다
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"signature_menu": "x"})], "b.json"))
    got = api.get_hours([_pid(db_session, "permit", "R1"), _pid(db_session, "permit", "R2")], db=db_session)
    assert sorted(h.closed_days[0] for h in got.values()) == ["월", "화"]


def test_same_place_twice_in_one_file_last_wins(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["월"]}), _entry("rest_R1", {"closed_days": ["화"]})]))
    assert next(iter(api.get_hours([_pid(db_session, "permit", "R1")], db=db_session).values())).closed_days == ["화"]


def test_rows_go_away_with_the_place(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": []})]))
    db_session.delete(db_session.get(Place, _pid(db_session, "permit", "R1")))
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(PlaceHours)) == 0


def test_cli_dry_run_writes_nothing_and_missing_file_exits_2(db_session, tmp_path, capsys):
    _seed(db_session, ("permit", "R1"))
    db_session.commit()
    path = _write(tmp_path, [_entry("rest_R1", {"closed_days": []})])
    db_session.close = lambda: None   # type: ignore[method-assign]
    assert load.main(["place-hours", "--file", str(path), "--dry-run"], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "place_hours upsert 1" in out and "dry-run" in out
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(PlaceHours)) == 0
    assert load.main(["place-hours", "--file", str(tmp_path / "none.json")], session_factory=lambda: db_session) == 2


def test_label_loading_commands_still_ignore_info(db_session, tmp_path):
    """restaurants 적재는 info를 읽지 않는다(place-hours 단계가 따로 읽는다) — 행이 생기지 않는다."""
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("관리번호,사업장명,업태,도로명주소,위도,경도\nR1,식당,한식,서울특별시 성동구 1,37.5,127.0\n", encoding="utf-8")
    labels = _write(tmp_path, [{"place_id": "rest_R1", "labels": {}, "info": {"closed_days": ["월"]}}])
    constraints = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"
    load.load_restaurants(db_session, csv_path, labels=labels, constraints=constraints, exclude_bars=False)
    assert db_session.scalar(select(func.count()).select_from(PlaceHours)) == 0


# ---- 요일 단위 판정 (#747) ----

def test_day_open_status_hours_key_wins():
    hours = _week(월=[["11:00", "21:00"]])
    assert core.day_open_status(hours, None, 0) == "open"
    assert core.day_open_status(hours, None, 1) == "closed"   # 빈 목록 = 휴무
    assert core.day_open_status({"월": [["11:00", "21:00"]]}, ["월"], 0) == "open"   # hours와 closed_days가 어긋나면 hours가 이긴다
    assert core.day_open_status(_week(), ["월"], 0) == "closed"


def test_day_open_status_falls_back_to_closed_days():
    assert core.day_open_status(None, ["월"], 0) == "closed"
    assert core.day_open_status(None, ["월"], 1) == "open"
    assert core.day_open_status({"월": []}, ["화"], 1) == "closed"   # hours에 그 요일 키가 없으면 closed_days로 넘어간다
    assert core.day_open_status({"월": []}, ["화"], 2) == "open"


def test_day_open_status_empty_closed_days_means_open_every_day():
    assert [core.day_open_status(None, [], d) for d in range(7)] == ["open"] * 7


def test_day_open_status_unknown_when_nothing_is_known():
    assert core.week_open_status(None, None) == {d: "unknown" for d in range(7)}
    assert core.week_open_status({}, None) == {d: "unknown" for d in range(7)}


def test_day_open_status_rejects_bad_weekday():
    with pytest.raises(ValueError):
        core.day_open_status(None, None, 7)


def test_week_open_status_ignores_yesterdays_tail_but_is_open_on_sees_it():
    hours = _week(금=[["18:00", "26:00"]])   # 토요일은 비었다
    assert core.week_open_status(hours, None)[5] == "closed"
    assert core.is_open_on(hours, None, 5, _m("01:00")) == "open"


def test_api_week_open_status_is_the_pure_rule():
    hours = _week(수=[["09:00", "18:00"]])
    got = api.week_open_status(hours, None)
    assert got == {d: ("open" if d == 2 else "closed") for d in range(7)}


def test_get_week_open_status_omits_places_without_a_row(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"), ("permit", "R2"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["월"]})]))
    r1, r2 = _pid(db_session, "permit", "R1"), _pid(db_session, "permit", "R2")
    got = api.get_week_open_status([r1, r2, "not-a-uuid"], db=db_session)
    assert set(got) == {r1}
    assert got[r1][0] == "closed" and got[r1][1] == "open"
    assert api.get_week_open_status([], db=db_session) == {}


# ---- 여러 요일의 영업 여부 (#747) ----

@pytest.mark.parametrize("hours, closed_days, weekdays, expected", [
    (_week(월=[["09:00", "18:00"]]), None, [0], "open"),
    (_week(월=[["09:00", "18:00"]]), None, [1, 2], "closed"),          # 쓰인 요일은 모두 닫았다
    (_week(월=[["09:00", "18:00"]]), None, [0, 1, 2], "open"),         # 하나라도 열면 open
    (None, ["월"], [0], "closed"),
    (None, ["월"], [0, 1], "open"),                                    # 휴무가 아닌 요일은 영업
    (None, None, [0, 1], "unknown"),                                   # 칸이 비어 있다
    (None, ["월"], [], "unknown"),                                     # 요일이 없으면 모름
])
def test_open_status_on_weekdays_pure_rule(hours, closed_days, weekdays, expected):
    assert api.open_status_on_weekdays(hours, closed_days, weekdays) == expected


def test_open_status_on_weekdays_unknown_days_do_not_count_as_closed():
    assert core.open_status_on_weekdays({0: "closed", 1: "unknown"}, [0, 1]) == "unknown"
    assert core.open_status_on_weekdays({0: "closed"}, [0, 3]) == "unknown"   # 상태에 없는 요일은 모름
    assert core.open_status_on_weekdays(None, [0]) == "unknown"


def test_get_open_status_on_weekdays_omits_places_without_a_row(db_session, tmp_path):
    _seed(db_session, ("permit", "R1"), ("permit", "R2"))
    load.load_place_hours(db_session, _write(tmp_path, [_entry("rest_R1", {"closed_days": ["월"]})]))
    r1, r2 = _pid(db_session, "permit", "R1"), _pid(db_session, "permit", "R2")
    assert api.get_open_status_on_weekdays([r1, r2], [0], db=db_session) == {r1: "closed"}
    assert api.get_open_status_on_weekdays([r1], [0, 1], db=db_session) == {r1: "open"}
    assert api.get_open_status_on_weekdays([], [0], db=db_session) == {}


# ---- 잘못된 원본 값은 모름이다 (#885 검수) ----

@pytest.mark.parametrize("hours, closed_days", [
    (None, ["월요일"]),                                   # 허용 형식이 아닌 요일 이름
    (None, "월"),                                         # 목록이 아니다
    (None, ["월", 3]),
    ({"월": [["잘못된 시각", "잘못된 시각"]]}, None),      # 시각 형식이 틀리다
    ({"월": [["09:00"]]}, None),                          # 구간이 두 칸이 아니다
    ({"월": [["18:00", "09:00"]]}, None),                 # 시작이 끝보다 늦다
    ({"월": "09:00-18:00"}, None),                        # 목록이 아니다
    ({"Mon": [["09:00", "18:00"]]}, None),                # 요일 이름이 아니다
    ("월 영업", None),
])
def test_malformed_raw_values_are_unknown_not_open(hours, closed_days):
    assert api.week_open_status(hours, closed_days) == {d: "unknown" for d in range(7)}
    assert api.open_status_on_weekdays(hours, closed_days, [0, 1, 2]) == "unknown"


def test_a_malformed_day_is_dropped_but_the_good_days_and_closed_days_still_apply():
    hours = {"월": [["잘못된 시각", "?"]], "화": [["09:00", "18:00"]]}
    got = api.week_open_status(hours, ["수"])
    assert got[0] == "open"       # 월은 hours에서 빠졌고 closed_days에도 없다 → closed_days가 있으니 영업
    assert got[1] == "open" and got[2] == "closed"


def test_core_valid_helpers_are_what_ingest_uses():
    assert core.valid_closed_days(["월", "월", "화"]) == ["월", "화"] and core.valid_closed_days([]) == []
    assert core.valid_hours(_week(월=[["09:00", "18:00"]])) is not None
    assert core.valid_hours({"월": []}) is None   # 7요일이 다 있어야 한다(적재용)


@pytest.mark.parametrize("clock", ["0009:00", "9:00", "09:0", "09:000", " 09:00", "09:00 ", "９:００", "09-00", "+9:00", "٠٩:٠٠"])
def test_raw_api_reads_a_clock_that_is_not_exactly_hh_mm_as_unknown(clock):
    hours = {"월": [[clock, "18:00"]]}
    assert api.week_open_status(hours, None) == {d: "unknown" for d in range(7)}
    hours = {"월": [["09:00", clock]]}
    assert api.week_open_status(hours, None) == {d: "unknown" for d in range(7)}


def test_raw_api_still_accepts_midnight_crossing_hh_mm():
    assert api.week_open_status({"금": [["18:00", "26:00"]]}, None)[4] == "open"


def test_ingest_keeps_its_own_clock_range():
    assert core.valid_hours(_week(월=[["9:00", "18:00"]])) is not None   # 적재 규칙은 그대로(parse_minutes가 받는 범위)

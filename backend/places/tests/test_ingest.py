"""적재 변환(순수) — 폐업 제외·좌표 변환·업태 대응·서울 필터·TourAPI·라벨 파일. 가짜 픽스처(실제 상호 아님)로 돈다."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from places import ingest
from places.load import read_csv_rows

FIX = Path(__file__).parent / "fixtures"
CONSTRAINTS = Path(__file__).resolve().parents[3] / "docs" / "constraints.md"


@pytest.fixture(scope="module")
def permit():
    rows, report = ingest.parse_permit_rows(read_csv_rows(FIX / "permit_sample.csv"))
    return {r.source_id: r for r in rows if True}, rows, report


# ---- 좌표 변환 ----

def test_projected_coords_are_converted_to_wgs84(permit):
    by_id, _, _ = permit
    p = by_id["P001"]
    assert (p.lat, p.lng) == pytest.approx((37.5445, 127.0561), abs=1e-5)


def test_values_already_in_lat_lng_are_left_alone(permit):
    by_id, _, _ = permit
    assert (by_id["P030"].lat, by_id["P030"].lng) == (37.5666, 126.9784)   # x=경도, y=위도 순서로 읽는다


def test_to_wgs84_swaps_xy_into_lat_lng_and_respects_crs():
    assert ingest.to_wgs84(127.0, 37.5, "EPSG:5174") == (37.5, 127.0)
    lat, lng = ingest.to_wgs84(198022.1, 451590.9, "EPSG:5174")   # 서울시청 부근
    assert (lat, lng) == pytest.approx((37.5666, 126.9784), abs=1e-4)
    lat2, lng2 = ingest.to_wgs84(198091.7, 551896.1, "EPSG:5186")  # 같은 지점, 다른 좌표계
    assert (lat2, lng2) == pytest.approx((37.5666, 126.9784), abs=1e-4)


def test_wrong_crs_that_lands_outside_korea_is_skipped_and_warned():
    rows = read_csv_rows(FIX / "permit_sample.csv")
    out, report = ingest.parse_permit_rows(rows, crs="EPSG:3857")   # 일부러 틀린 좌표계
    assert out == [] or all(ingest.in_korea(r.lat, r.lng) for r in out)
    assert any("--crs" in w for w in report.warnings)


def test_coordinates_far_outside_korea_are_skipped(permit):
    _, rows, report = permit
    assert "P046" not in {r.source_id for r in rows}
    assert report.skipped["좌표가 한국 범위 밖(좌표계 확인)"] == 1


# ---- 폐업·상태 ----

def test_closed_statuses_are_marked_closed_not_open(permit):
    by_id, _, _ = permit
    assert {i: by_id[i].status for i in ("P020", "P021", "P022")} == {"P020": "closed", "P021": "closed", "P022": "closed"}
    assert all(by_id[i].status == "open" for i in ("P001", "P010", "P030"))


def test_unknown_status_is_skipped_and_counted(permit):
    _, rows, report = permit
    assert "P044" not in {r.source_id for r in rows}
    assert report.skipped["알 수 없는 영업상태: 준비중"] == 1


def test_detail_status_is_used_when_status_is_blank():
    assert ingest.permit_status("", "폐업") == "closed"
    assert ingest.permit_status("영업/정상", "") == "open"
    assert ingest.permit_status("모름", "") is None


# ---- 업태 대응 ----

@pytest.mark.parametrize("raw,expected", [
    ("한식", "음식점"), ("중식", "음식점"), ("분식", "음식점"), ("김밥(도시락)", "음식점"), ("외국음식전문점(인도,태국등)", "음식점"),
    ("카페", "카페"), ("까페", "카페"), ("다방", "카페"), ("제과점영업", "카페"), ("커피숍", "카페"),
    ("감성주점", None), ("정종/대포집/소주방", None), ("", None), ("룸살롱", None),
])
def test_business_type_mapping(raw, expected):
    assert ingest.map_permit_category(raw) == expected


def test_mapping_ignores_whitespace():
    assert ingest.map_permit_category(" 커피 숍 ") == "카페"


def test_unmapped_types_are_skipped_and_reported(permit):
    by_id, _, report = permit
    assert "P041" not in by_id and "P047" not in by_id
    assert report.skipped["업태 대응표에 없음"] == 2
    assert any("감성주점" in w for w in report.warnings)
    assert by_id["P010"].category == "카페" and by_id["P011"].category == "카페"   # 까페도 카페
    assert by_id["P001"].category == "음식점"


# ---- 서울 필터 · 좌표 없음 · 필수값 ----

def test_non_seoul_and_missing_address_rows_are_skipped(permit):
    _, rows, report = permit
    ids = {r.source_id for r in rows}
    assert "P042" not in ids and "P043" not in ids
    assert report.skipped["서울 아님(또는 주소 없음)"] == 2


def test_rows_without_coordinates_are_skipped(permit):
    _, rows, report = permit
    assert "P040" not in {r.source_id for r in rows}
    assert report.skipped["좌표 없음"] == 1


def test_rows_without_id_or_name_are_skipped(permit):
    _, _, report = permit
    assert report.skipped["관리번호 또는 사업장명 없음"] == 1


def test_all_regions_flag_keeps_non_seoul():
    rows = read_csv_rows(FIX / "permit_sample.csv")
    out, _ = ingest.parse_permit_rows(rows, seoul_only=False)
    assert "P042" in {r.source_id for r in out}


def test_report_adds_up(permit):
    _, rows, report = permit
    assert report.read == 25 and report.accepted == len(rows) == 17
    assert report.accepted + sum(report.skipped.values()) == report.read


def test_header_variants_and_bom_are_tolerated():
    row = {"﻿관리번호": "X1", " 사업장명 ": "공백 헤더", "영업상태명": "영업/정상", "업태구분명": "한식",
           "소재지전체주소": "서울특별시 중구 1", "좌표정보(x)": "126.97", "좌표정보(y)": "37.56"}
    out, _ = ingest.parse_permit_rows([row])
    assert out[0].name == "공백 헤더" and out[0].address == "서울특별시 중구 1"


def test_read_csv_rows_falls_back_to_cp949(tmp_path):
    path = tmp_path / "cp949.csv"
    path.write_bytes("관리번호,사업장명\nA1,한글 상호\n".encode("cp949"))
    assert read_csv_rows(path) == [{"관리번호": "A1", "사업장명": "한글 상호"}]


# ---- TourAPI ----

@pytest.fixture(scope="module")
def tour():
    payload = json.loads((FIX / "tourapi_items.json").read_text(encoding="utf-8"))
    return ingest.parse_tourapi_items(ingest.extract_tourapi_items(payload))


def test_tourapi_keeps_only_seoul_tourist_spots(tour):
    rows, report = tour
    assert [r.source_id for r in rows] == ["T100", "T101", "T102"]
    assert {r.category for r in rows} == {"관광지"} and {r.source for r in rows} == {"tourapi"}
    assert report.read == 8 and report.accepted == 3


def test_tourapi_does_not_take_lodging(tour):
    _, report = tour
    assert report.skipped["숙박은 받지 않는다"] == 1
    assert report.skipped["관광지·문화시설·쇼핑(contenttypeid=12·14·38) 아님"] == 1   # 음식점(39)


def test_tourapi_mapx_is_lng_and_mapy_is_lat(tour):
    rows, _ = tour
    assert (rows[0].lat, rows[0].lng) == (37.5444, 127.0374)


def test_tourapi_skips_other_regions_missing_coords_and_missing_title(tour):
    _, report = tour
    assert report.skipped["서울 아님"] == 1 and report.skipped["좌표 없음"] == 1 and report.skipped["contentid 또는 title 없음"] == 1


def test_tourapi_address_joins_addr1_and_addr2(tour):
    rows, _ = tour
    assert rows[1].address == "서울특별시 종로구 사직로 161 (세종로)"


def _tour_item(ctype: str, cid: str, *, mapx: str = "126.9770", mapy: str = "37.5796", addr: str = "서울특별시 종로구 사직로 161") -> dict:
    return {"contentid": cid, "contenttypeid": ctype, "title": f"장소{cid}", "addr1": addr, "mapx": mapx, "mapy": mapy, "areacode": ""}


def test_tourapi_takes_tourist_spot_culture_and_market_as_tourist_category():
    rows, report = ingest.parse_tourapi_items([_tour_item("12", "1"), _tour_item("14", "2"), _tour_item("38", "3"), _tour_item("32", "4")])
    assert [r.source_id for r in rows] == ["1", "2", "3"]
    assert {r.category for r in rows} == {"관광지"}
    assert report.skipped["숙박은 받지 않는다"] == 1
    assert report.accepted_by_type == {"12": 1, "14": 1, "38": 1} and report.skipped_by_type == {"32": 1}
    assert "  [contenttypeid 14] 받음 1 / 건너뜀 0" in report.lines()
    assert "  [contenttypeid 32] 받음 0 / 건너뜀 1" in report.lines()


def test_tourapi_skips_coords_outside_seoul_even_with_seoul_address():
    wrong = _tour_item("12", "128933", mapx="127.709322", mapy="37.470571", addr="서울특별시 관악구 관악로 173")
    rows, report = ingest.parse_tourapi_items([wrong, _tour_item("12", "1")])
    assert [r.source_id for r in rows] == ["1"]
    assert report.skipped["서울 밖 좌표"] == 1
    assert "  - 서울 밖 좌표: 1" in report.lines()
    kept, _ = ingest.parse_tourapi_items([wrong], seoul_only=False)
    assert [r.source_id for r in kept] == ["128933"]


def test_extract_tourapi_items_shapes():
    one = {"response": {"body": {"items": {"item": {"contentid": "1"}}}}}   # 한 건이면 dict로 온다
    assert ingest.extract_tourapi_items(one) == [{"contentid": "1"}]
    assert ingest.extract_tourapi_items([{"a": 1}, "x"]) == [{"a": 1}]
    assert ingest.extract_tourapi_items({"response": {"body": {"items": ""}}}) == []
    assert ingest.extract_tourapi_items(None) == []


# ---- 라벨 파일 ----

@pytest.fixture(scope="module")
def labels():
    allowed = ingest.allowed_fact_keys_from_constraints(CONSTRAINTS.read_text(encoding="utf-8"))
    return allowed, *ingest.parse_label_rows(read_csv_rows(FIX / "labels.csv"), allowed)


def test_allowed_keys_come_from_constraints_md_without_code_judged_ones(labels):
    allowed, _, _ = labels
    assert {"spicy_focused", "quiet", "good_view", "contains_shellfish"} <= allowed
    assert "is_open" not in allowed and "within_radius" not in allowed
    assert "price_bucket" not in allowed   # #423에서 뺐다


def test_label_rows_known_unknown_and_layers(labels):
    _, rows, _ = labels
    by_key = {(r.source_id, r.fact_key): r for r in rows}
    assert by_key[("P001", "contains_shellfish")].value is True
    assert by_key[("P001", "contains_shellfish")].source_layer == 3
    unknown = by_key[("P001", "oily_focused")]
    assert unknown.confidence == "unknown" and unknown.value is None
    assert by_key[("T100", "good_view")].value is True   # TRUE도 받는다
    assert by_key[("T100", "quiet")].labeled_at == datetime(2026, 9, 30, 12, 0)


def test_unknown_fact_keys_are_skipped_and_counted(labels):
    _, rows, report = labels
    assert report.skipped["모르는 fact_key: made_up_key"] == 1
    assert report.skipped["모르는 fact_key: is_open"] == 1        # 코드 판정 키는 라벨 대상이 아니다
    assert all(r.fact_key != "made_up_key" for r in rows)


def test_contains_prefix_keys_are_allowed_even_if_not_listed(labels):
    _, rows, _ = labels
    assert any(r.fact_key == "contains_peanut" for r in rows)


def test_retired_price_bucket_rows_are_skipped_whatever_the_value(labels):
    """#423 — 납품 파일에 남은 가격대 줄(mid, 원본 숫자 12000)은 등록 안 된 키라 건너뛴다."""
    _, rows, report = labels
    assert report.skipped["모르는 fact_key: price_bucket"] == 2
    assert all(r.fact_key != "price_bucket" for r in rows)


def test_bad_boolean_bad_confidence_bad_source_are_skipped(labels):
    _, _, report = labels
    assert report.skipped["known인데 value가 true/false가 아님"] == 1
    assert report.skipped["confidence가 known/unknown이 아님"] == 1
    assert report.skipped["source/source_id 이상"] == 1


def test_duplicate_label_keys_last_row_wins_with_warning(labels):
    _, rows, report = labels
    spicy = [r for r in rows if (r.source_id, r.fact_key) == ("P001", "spicy_focused")]
    assert len(spicy) == 1 and spicy[0].value is True   # 앞 줄 false, 뒷 줄 true
    assert any("마지막 줄" in w for w in report.warnings)


def test_unknown_confidence_ignores_a_given_value():
    allowed = frozenset({"quiet"})
    rows, _ = ingest.parse_label_rows([{"source": "permit", "source_id": "P1", "fact_key": "quiet", "value": "true", "confidence": "unknown"}], allowed)
    assert rows[0].value is None


# ---- 음식점 납품본 (#207) ----

@pytest.fixture(scope="module")
def curated():
    rows, report = ingest.parse_curated_rows(read_csv_rows(FIX / "restaurant_curated_sample.csv"))
    return {r.source_id: r for r in rows}, rows, report


def test_curated_rows_use_given_lat_lng_without_conversion(curated):
    by_id, _, _ = curated
    p = by_id["R001"]
    assert (p.lat, p.lng) == (37.5704, 126.9920)   # 이미 WGS84 위도/경도 — 변환하지 않는다
    assert (p.source, p.source_id, p.category, p.status) == ("permit", "R001", "음식점", "open")
    assert p.address == "서울특별시 종로구 가상로 1 (가상동)" and p.phone == "027359996"


def test_curated_everything_is_a_restaurant_and_open(curated):
    _, rows, _ = curated
    assert {r.category for r in rows} == {"음식점"} and {r.status for r in rows} == {"open"}


def test_curated_rows_without_coordinates_are_skipped_and_counted(curated):
    by_id, _, report = curated
    assert "R009" not in by_id and "R010" not in by_id   # 위도·경도 둘 다 / 위도만 비어도 건너뜀
    assert report.skipped["좌표 없음"] == 2


def test_curated_skips_non_seoul_out_of_range_and_missing_id(curated):
    by_id, _, report = curated
    assert "R012" not in by_id and "R013" not in by_id
    assert report.skipped["서울 아님(또는 주소 없음)"] == 1
    assert report.skipped["좌표가 한국 범위 밖"] == 1
    assert report.skipped["관리번호 또는 사업장명 없음"] == 1


def test_curated_report_adds_up_and_blank_type_is_kept_with_warning(curated):
    by_id, rows, report = curated
    assert report.read == 14 and report.accepted == len(rows) == 9
    assert report.accepted + sum(report.skipped.values()) == report.read
    assert "R011" in by_id and any("R011" in w for w in report.warnings)


def test_curated_bar_types_are_included_by_default_but_reported(curated):
    by_id, _, report = curated
    assert "R007" in by_id and "R008" in by_id
    assert any("유흥·주점류" in w and "2행" in w and "포함" in w for w in report.warnings)


def test_curated_exclude_bars_flag_drops_them_and_counts():
    rows, report = ingest.parse_curated_rows(read_csv_rows(FIX / "restaurant_curated_sample.csv"), exclude_bars=True)
    ids = {r.source_id for r in rows}
    assert "R007" not in ids and "R008" not in ids and "R001" in ids
    assert report.skipped["유흥·주점류 제외(--exclude-bars): 정종/대포집/소주방"] == 1
    assert report.skipped["유흥·주점류 제외(--exclude-bars): 감성주점"] == 1


def test_curated_bom_header_is_read():
    rows = read_csv_rows(FIX / "restaurant_curated_sample.csv")
    assert "관리번호" in rows[0]   # utf-8-sig로 BOM이 벗겨진다


# ---- 납품본 라벨 JSON → 기존 라벨 경로 ----

NEW_KEYS = frozenset({
    "cuisine_korean", "cuisine_chinese", "spacious", "long_established", "franchise", "spicy_focused", "oily_focused",
    "contains_shellfish", "wait_short", "pet_friendly", "quiet",
})


@pytest.fixture(scope="module")
def curated_labels():
    entries = json.loads((FIX / "restaurant_curated_labels.json").read_text(encoding="utf-8"))
    return ingest.parse_label_rows(ingest.curated_labels_to_rows(entries), NEW_KEYS)


def test_rest_prefix_is_stripped_and_source_is_permit(curated_labels):
    rows, _ = curated_labels
    assert {(r.source, r.source_id) for r in rows} == {("permit", "R001"), ("permit", "R002"), ("permit", "R007"), ("permit", "R404"), ("permit", "R003")}


def test_string_values_become_bool_and_unknown_has_no_value(curated_labels):
    rows, _ = curated_labels
    by = {(r.source_id, r.fact_key): r for r in rows}
    assert by[("R001", "cuisine_korean")].value is True and by[("R001", "cuisine_chinese")].value is False
    unknown = by[("R001", "contains_shellfish")]
    assert (unknown.confidence, unknown.value) == ("unknown", None)
    assert by[("R001", "wait_short")].confidence == "unknown" and by[("R001", "pet_friendly")].confidence == "unknown"


def test_evidence_and_label_source_are_carried(curated_labels):
    rows, _ = curated_labels
    by = {(r.source_id, r.fact_key): r for r in rows}
    assert by[("R001", "spicy_focused")].evidence == "가게 이름 '짬뽕'"
    assert by[("R001", "spicy_focused")].label_source == "menu_keyword"
    assert by[("R001", "contains_shellfish")].evidence is None   # 근거 없는 unknown


def test_unregistered_keys_wrong_values_and_bad_ids_are_skipped_and_counted(curated_labels):
    rows, report = curated_labels
    assert report.skipped["모르는 fact_key: made_up_key"] == 1
    assert report.skipped["모르는 fact_key: long_established"] == 0   # NEW_KEYS에 있으니 통과
    assert report.skipped["모르는 fact_key: price_bucket"] == 2        # R001 low, R003 가격 숫자 — #423에서 뺀 키
    assert report.skipped["known인데 value가 true/false가 아님"] == 1   # quiet=maybe
    assert report.skipped["source/source_id 이상"] == 1                # weird_R001
    assert all(r.fact_key != "made_up_key" for r in rows)


def test_keys_missing_from_constraints_are_reported_as_unregistered():
    """#206 머지 전 상태(신규 15개 미등록)를 흉내 낸다 — 건너뛰고 키별로 센다."""
    entries = json.loads((FIX / "restaurant_curated_labels.json").read_text(encoding="utf-8"))
    old = frozenset({"spicy_focused", "oily_focused", "contains_shellfish", "wait_short", "pet_friendly"})
    rows, report = ingest.parse_label_rows(ingest.curated_labels_to_rows(entries), old)
    assert report.skipped["모르는 fact_key: cuisine_korean"] == 3   # R001, R007, R404, weird_R001은 id 이상보다 키 검사가 먼저
    assert all(r.fact_key in old for r in rows)


# ---- 카페 납품본 (#266) ----

@pytest.fixture()
def cafes():
    rows, report = ingest.parse_cafe_rows(read_csv_rows(FIX / "cafe_curated_sample.csv"))
    return {r.source_id: r for r in rows}, report


def test_cafe_rows_are_loaded_as_cafe_category_permit_source_with_given_coordinates(cafes):
    by_id, _ = cafes
    assert set(by_id) == {f"C00{i}" for i in range(1, 9)}   # 업태 8종 8곳
    assert {r.category for r in by_id.values()} == {"카페"} and {r.source for r in by_id.values()} == {"permit"}
    assert {r.status for r in by_id.values()} == {"open"}
    assert (by_id["C001"].lat, by_id["C001"].lng) == (37.5446, 127.0562)


def test_cafe_unknown_business_types_and_missing_coordinates_are_skipped_and_counted(cafes):
    by_id, report = cafes
    assert report.skipped["좌표 없음"] == 1 and "C009" not in by_id
    assert report.skipped["모르는 업태: 북카페"] == 1 and "C010" not in by_id
    assert report.skipped["모르는 업태: (비어 있음)"] == 1 and "C011" not in by_id
    assert report.skipped["서울 아님(또는 주소 없음)"] == 1 and "C012" not in by_id
    assert report.read == 12 and report.accepted == 8 and sum(report.skipped.values()) == 4


def test_cafe_type_table_has_the_eight_delivered_types():
    assert ingest.CURATED_CAFE_TYPES == {"커피숍", "제과점영업", "까페", "다방", "전통찻집", "라이브카페", "키즈카페", "떡카페"}


def test_restaurant_parser_is_unchanged_by_the_cafe_option():
    rows, _ = ingest.parse_curated_rows(read_csv_rows(FIX / "restaurant_curated_sample.csv"))
    assert {r.category for r in rows} == {"음식점"}


def test_label_json_reads_both_rest_and_cafe_prefixes():
    entries = [{"place_id": "rest_R1", "labels": {"quiet": {"value": "true"}}},
               {"place_id": "cafe_3000000-101-1995-02376", "labels": {"quiet": {"value": "true"}}},
               {"place_id": "other_X", "labels": {"quiet": {"value": "true"}}}]
    got = [(r["source"], r["source_id"]) for r in ingest.curated_labels_to_rows(entries)]
    assert got == [("permit", "R1"), ("permit", "3000000-101-1995-02376"), ("", "")]

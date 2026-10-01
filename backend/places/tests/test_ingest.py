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
    assert report.skipped["관광지(contenttypeid=12) 아님"] == 1   # 음식점(39)


def test_tourapi_mapx_is_lng_and_mapy_is_lat(tour):
    rows, _ = tour
    assert (rows[0].lat, rows[0].lng) == (37.5444, 127.0374)


def test_tourapi_skips_other_regions_missing_coords_and_missing_title(tour):
    _, report = tour
    assert report.skipped["서울 아님"] == 1 and report.skipped["좌표 없음"] == 1 and report.skipped["contentid 또는 title 없음"] == 1


def test_tourapi_address_joins_addr1_and_addr2(tour):
    rows, _ = tour
    assert rows[1].address == "서울특별시 종로구 사직로 161 (세종로)"


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
    assert {"spicy_focused", "price_bucket", "quiet", "good_view", "contains_shellfish"} <= allowed
    assert "is_open" not in allowed and "within_radius" not in allowed


def test_label_rows_known_unknown_and_layers(labels):
    _, rows, _ = labels
    by_key = {(r.source_id, r.fact_key): r for r in rows}
    assert by_key[("P001", "contains_shellfish")].value is True
    assert by_key[("P001", "price_bucket")].value == "mid" and by_key[("P001", "price_bucket")].source_layer == 2
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


def test_raw_price_numbers_are_rejected(labels):
    _, rows, report = labels
    assert report.skipped["price_bucket은 low/mid/high만(원본 가격 숫자 거부)"] == 1
    assert all(r.value != "12000" for r in rows)


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

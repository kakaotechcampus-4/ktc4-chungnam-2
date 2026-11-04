"""시·도 경계(#1385) — 로더(해시 확인·멱등·dry-run), sido_at 경계 판정과 되돌아가기, circle_outside_region, 실데이터."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from places import api, boundaries, load, repository
from places.models import SidoBoundary
from places.tests.test_cuisine_names_1093 import _NoClose

FE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "map" / "regionBoundaries"
REAL_DIR = Path(os.environ["PINGO_SIDO_DIR"]) if os.environ.get("PINGO_SIDO_DIR") else FE_DIR


def _square(lat0, lng0, lat1, lng1):
    return [[lat0, lng0], [lat0, lng1], [lat1, lng1], [lat1, lng0]]


def _put(db, code, name, polygons):
    wkt = boundaries.to_wkt(polygons)
    repository.upsert_boundaries(db, [{"code": code, "name": name, "wkt": wkt, "sha256": "x" * 64}])


# ---------------------------------------------------------------- 순수 함수

def test_every_code_has_a_name_and_a_hash():
    assert set(boundaries.SIDO_BY_CODE) == set(boundaries.EXPECTED_SHA256) and len(boundaries.SIDO_BY_CODE) == 17
    assert boundaries.SIDO_BY_CODE["24"] == boundaries.SIDO_BY_CODE["36"] == "전남광주"   # 2026 통합(#1059)


def test_to_wkt_swaps_to_lng_lat_closes_rings_and_keeps_holes():
    wkt = boundaries.to_wkt([[_square(37, 127, 38, 128), _square(37.4, 127.4, 37.6, 127.6)]])
    assert wkt.startswith("MULTIPOLYGON(((127.0 37.0,128.0 37.0")
    assert wkt.count("),(") == 1 and wkt.count("127.0 37.0") == 2   # 외곽 닫힘, 구멍은 별도 고리


@pytest.mark.parametrize("polygons", [[], [[[[37, 127], [37, 128]]]], [[[[0, 0], [0, 1], [1, 1]]]]])
def test_to_wkt_rejects_bad_shapes(polygons):
    with pytest.raises(boundaries.BoundaryFileError):
        boundaries.to_wkt(polygons)


def test_expected_hashes_match_the_ui_source_when_it_is_in_the_repo():
    if not FE_DIR.is_dir():
        pytest.skip("화면 경계 파일이 이 브랜치에 없다(#1386 병합 전)")
    for code, digest in boundaries.EXPECTED_SHA256.items():
        data = json.loads((FE_DIR / f"{code}.json").read_text(encoding="utf-8-sig"))
        assert boundaries.content_hash(data) == digest, f"{code}.json이 바뀌었다 — places/boundaries.py의 기대 해시를 같이 고친다"


# ---------------------------------------------------------------- 로더

@pytest.fixture()
def fake_folder(tmp_path, monkeypatch):
    """17개 합성 파일(코드마다 위도 띠 하나) + 그 해시를 기대값으로 둔다."""
    hashes = {}
    for i, code in enumerate(boundaries.SIDO_BY_CODE):
        data = [[_square(33 + i * 0.3, 126, 33.2 + i * 0.3, 127)]]
        (tmp_path / f"{code}.json").write_text(json.dumps(data), encoding="utf-8")
        hashes[code] = boundaries.content_hash(data)
    monkeypatch.setattr(boundaries, "EXPECTED_SHA256", hashes)
    return tmp_path


def _count(db):
    return db.scalar(select(func.count()).select_from(SidoBoundary))


def test_loader_is_idempotent_and_maps_names(db_session, fake_folder, capsys):
    run = lambda *extra: load.main(["boundaries", "--dir", str(fake_folder), *extra], session_factory=lambda: _NoClose(db_session))
    assert run() == 0 and _count(db_session) == 17
    assert run() == 0 and _count(db_session) == 17          # 같은 코드는 덮어쓴다
    names = dict(db_session.execute(select(SidoBoundary.code, SidoBoundary.name)).all())
    assert names["11"] == "서울" and names["24"] == names["36"] == "전남광주" and names["39"] == "제주"
    assert "upsert 17" in capsys.readouterr().out


def test_loader_dry_run_writes_nothing(db_session, fake_folder, capsys):
    assert load.main(["boundaries", "--dir", str(fake_folder), "--dry-run"], session_factory=lambda: _NoClose(db_session)) == 0
    db_session.rollback()   # 로더의 dry-run 롤백이 SAVEPOINT 안에서 끝난 뒤 본다
    assert _count(db_session) == 0 and "dry-run" in capsys.readouterr().out


def test_loader_rejects_a_changed_file_and_writes_nothing(db_session, fake_folder, capsys):
    (fake_folder / "11.json").write_text(json.dumps([[_square(37, 126, 38, 127)]]), encoding="utf-8")
    assert load.main(["boundaries", "--dir", str(fake_folder)], session_factory=lambda: _NoClose(db_session)) == 2
    assert "화면 정본과 다르다" in capsys.readouterr().err and _count(db_session) == 0


def test_loader_rejects_a_missing_file_and_a_missing_folder(db_session, fake_folder, tmp_path, capsys):
    (fake_folder / "39.json").unlink()
    assert load.main(["boundaries", "--dir", str(fake_folder)], session_factory=lambda: _NoClose(db_session)) == 2
    assert load.main(["boundaries", "--dir", str(tmp_path / "없는폴더")], session_factory=lambda: _NoClose(db_session)) == 2
    assert _count(db_session) == 0


def test_loader_ignores_line_endings(db_session, fake_folder):
    path = fake_folder / "11.json"
    path.write_bytes(json.dumps(json.loads(path.read_text()), indent=2).replace("\n", "\r\n").encode())   # 줄바꿈·들여쓰기만 다르다
    assert load.main(["boundaries", "--dir", str(fake_folder)], session_factory=lambda: _NoClose(db_session)) == 0


# ---------------------------------------------------------------- sido_at · circle_outside_region (합성 경계)

@pytest.fixture()
def synthetic(db_session):
    # "서울" = 위도 37~38, 경도 127~128 사각형, 가운데 구멍(37.4~37.6, 127.4~127.6), 섬(36.5~36.6, 127.2~127.3). "경기" = 서울 서쪽 이웃
    _put(db_session, "11", "서울", [[_square(37, 127, 38, 128), _square(37.4, 127.4, 37.6, 127.6)], [_square(36.5, 127.2, 36.6, 127.3)]])
    _put(db_session, "31", "경기", [[_square(37, 126, 38, 127)]])
    return db_session


@pytest.mark.parametrize("lat, lng, expected", [
    (37.2, 127.5, "서울"), (37.2, 126.5, "경기"),
    (37.5, 127.5, None),    # 구멍
    (36.55, 127.25, "서울"),  # 떨어진 섬
    (39.0, 127.5, None), (35.0, 131.0, None),
])
def test_sido_at_uses_the_boundary(synthetic, lat, lng, expected):
    assert api.sido_at(lat, lng, db=synthetic) == expected


def test_sido_at_falls_back_to_the_nearest_place_when_the_table_is_empty(db_session):
    from places.models import Place

    db_session.add(Place(source="permit", source_id="b1", name="가게", category="음식점", address="부산광역시 해운대구 1", geom="SRID=4326;POINT(129.16 35.16)"))
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(SidoBoundary)) == 0
    assert api.sido_at(35.1587, 129.1604, db=db_session) == "부산"
    assert api.sido_at(33.4996, 126.5312, db=db_session) is None


def test_circle_outside_region_cases(synthetic):
    f = lambda lat, lng, r, s="서울": api.circle_outside_region(lat, lng, r, s, db=synthetic)
    assert f(37.2, 127.5, 3000) is False          # 안
    assert f(37.2, 127.002, 3000) is False        # 걸침(서쪽 경계 위)
    assert f(37.2, 126.9, 500) is True            # 경기 쪽, 8km 떨어짐
    assert f(37.5, 127.5, 3000) is True           # 원 전체가 구멍 안(구멍 반폭 약 8.8km) = 서울 밖
    assert f(37.5, 127.5, 10000) is False         # 구멍 둘레에 닿는다
    assert f(36.55, 127.25, 500) is False         # 섬
    assert f(37.2, 127.5, 3000, "없는시도") is None
    assert f(35.0, 131.0, 3000) is True           # 바다 위


def test_circle_uses_geography_not_a_flat_circle(synthetic):
    # 위도 37.5에서 경도 1°는 약 88km(적도의 111km가 아니다). 서울 동쪽 경계(127.99… 아닌 128.0)에서 동쪽으로 0.06° ≈ 5.3km
    lat, lng = 37.2, 128.06
    assert api.circle_outside_region(lat, lng, 5000, "서울", db=synthetic) is True
    assert api.circle_outside_region(lat, lng, 5600, "서울", db=synthetic) is False     # 평면(1°=111km) 근사면 6.7km라 True로 틀린다


def test_circle_outside_region_is_none_when_the_table_is_empty(db_session):
    assert api.circle_outside_region(37.5, 127.0, 3000, "서울", db=db_session) is None


def test_a_union_name_spans_both_rows(db_session):
    _put(db_session, "24", "전남광주", [[_square(35, 126, 35.3, 127)]])
    _put(db_session, "36", "전남광주", [[_square(34, 126, 35, 127)]])
    assert api.sido_at(35.1, 126.5, db=db_session) == "전남광주" and api.sido_at(34.5, 126.5, db=db_session) == "전남광주"
    assert api.circle_outside_region(34.5, 126.5, 2000, "전남광주", db=db_session) is False


# ---------------------------------------------------------------- 실데이터(통계청 2018 경계 17개) — 화면 파일이 이 브랜치에 있거나 PINGO_SIDO_DIR이 있을 때

@pytest.fixture()
def real(db_session, tmp_path):
    if not (REAL_DIR / "11.json").is_file():
        pytest.skip("실제 경계 파일이 없다(화면 정본은 #1386 병합 뒤, 또는 PINGO_SIDO_DIR)")
    folder = tmp_path / "sido"
    shutil.copytree(REAL_DIR, folder)
    assert load.main(["boundaries", "--dir", str(folder)], session_factory=lambda: _NoClose(db_session)) == 0
    return db_session


@pytest.mark.parametrize("lat, lng, expected", [
    (37.5445, 127.0557, "서울"), (35.1587, 129.1604, "부산"), (36.3504, 127.3845, "대전"), (33.4996, 126.5312, "제주"),
    (37.5, 131.0, None), (35.68, 139.7, None),   # 동해, 도쿄
    (35.1595, 126.8526, "전남광주"), (34.76, 127.66, "전남광주"), (37.2636, 127.0286, "경기"), (37.4563, 126.7052, "인천"),
])
def test_real_boundaries_sido_at(real, lat, lng, expected):
    assert api.sido_at(lat, lng, db=real) == expected


def test_real_boundaries_seoul_gyeonggi_border(real):
    # 서울 강남과 성남(분당 쪽) — 서울 도심에서 남동쪽으로 가다 보면 경기로 바뀐다
    assert api.sido_at(37.4979, 127.0276, db=real) == "서울"        # 강남역
    assert api.sido_at(37.3595, 127.1052, db=real) == "경기"        # 분당 서현
    assert api.sido_at(37.7380, 126.7480, db=real) == "경기"        # 파주 쪽


def test_real_boundaries_circle_cases(real):
    assert api.circle_outside_region(37.5665, 126.9780, 3000, "서울", db=real) is False   # 서울 도심은 서울을 걸친다
    assert api.circle_outside_region(37.5, 131.0, 3000, "서울", db=real) is True          # 바다 위
    assert api.circle_outside_region(33.4996, 126.5312, 3000, "서울", db=real) is True    # 제주 도심은 서울 밖
    assert api.circle_outside_region(33.4996, 126.5312, 3000, "제주", db=real) is False
    assert api.circle_outside_region(37.5665, 126.9780, 3000, "경기", db=real) is True    # 도심 3km 원은 경기에 닿지 않는다


def test_real_boundaries_calls_are_fast(real):
    api.sido_at(37.5445, 127.0557, db=real)   # 첫 호출은 계획·캐시를 데운다
    start = time.perf_counter()
    for _ in range(20):
        api.sido_at(37.5445, 127.0557, db=real)
        api.circle_outside_region(37.5665, 126.9780, 3000, "서울", db=real)
    assert (time.perf_counter() - start) / 40 < 0.05   # 호출당 50ms 아래


def test_real_boundary_table_has_a_gist_index(real):
    index = real.scalar(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'sido_boundaries' AND indexdef ILIKE '%gist%'"))
    assert index and "geom" in index

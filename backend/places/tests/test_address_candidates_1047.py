"""주소 후보(#1047) — 이름이 달라도 같은 도로명주소에 한 곳뿐이면 후보, 지점 접미사, 구글 링크 이름 속 주소 분리. 실제 공유 글 샘플."""

import pytest
from sqlalchemy import func

from common.errors import AppError
from places import api, linkparse, matching, repository
from places.matching import split_address_and_name, strip_branch_suffix
from places.models import Place
from places.testing import FakePlaces, _Row


def _add(db, sid, name, address, category="카페", status="open"):
    db.add(Place(source="permit", source_id=sid, name=name, category=category, address=address, status=status,
                 geom=func.ST_SetSRID(func.ST_MakePoint(126.99, 37.57), 4326)))
    db.flush()


@pytest.fixture()
def sample(db_session):
    _add(db_session, "1", "라타르타데라마드레데크리스코리아", "서울특별시 종로구 창덕궁1길 39, 1층 (와룡동)")
    _add(db_session, "2", "왕비집", "서울특별시 중구 명동8가길 26, 2층 (충무로2가)", "음식점")
    _add(db_session, "3", "입점 A", "대전광역시 중구 중앙로138번길 48 1층", "음식점")
    _add(db_session, "4", "입점 B", "대전광역시 중구 중앙로138번길 48 2층", "카페")
    _add(db_session, "5", "스타벅스 종로점", "서울특별시 종로구 종로 10")
    _add(db_session, "6", "스타벅스 안국점", "서울특별시 종로구 율곡로 20")
    _add(db_session, "7", "폐업 식당", "서울특별시 종로구 계동길 17", "음식점", status="closed")
    return db_session


# ---- 주소 후보 ----

def test_cheesecake_case_is_a_candidate_not_a_match(sample):
    got = api.match_address_candidates("서울 종로구 창덕궁1길 39 1층 라타르타", db=sample)
    assert [r.place_name for r in got] == ["라타르타데라마드레데크리스코리아"] and got[0].pinnable
    assert api.match_by_name_address("크리스엄마의 치즈케이크", "서울 종로구 창덕궁1길 39 1층 라타르타", db=sample) == []   # 이름 근거가 없어 확정하지 않는다


def test_multi_tenant_building_gives_nothing(sample):
    assert api.match_address_candidates("대전 중구 중앙로138번길 48", db=sample) == []


@pytest.mark.parametrize("address", [
    "서울 종로구 창덕궁1길 40",          # 다른 건물번호
    "서울 종로구 창덕궁1길",             # 건물번호 없음
    "서울 성동구 성수동2가 300-1",       # 지번은 이 조회를 하지 않는다
    "",
    "계동길 17",                         # 폐업만 있다
])
def test_nothing_when_address_cannot_be_pinned_down(sample, address):
    assert api.match_address_candidates(address, db=sample) == []


def test_too_many_rows_for_the_street_is_empty(sample, monkeypatch):
    monkeypatch.setattr(matching, "ADDRESS_CANDIDATE_MAX_ROWS", 0)
    assert api.match_address_candidates("서울 종로구 창덕궁1길 39", db=sample) == []


def test_address_is_not_logged(sample, caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        api.match_address_candidates("서울 종로구 창덕궁1길 39", db=sample)
    assert "창덕궁" not in caplog.text


# ---- 지점 접미사 ----

def test_branch_suffix_matches_when_the_address_agrees(sample):
    got = api.match_by_name_address("왕비집 명동본점", "서울특별시 중구 명동8가길 26", db=sample)
    assert [r.place_name for r in got] == ["왕비집"]


def test_branch_suffix_does_not_rescue_a_different_address(sample):
    assert api.match_by_name_address("스타벅스 종로점", "서울 종로구 율곡로 99", db=sample) == []
    assert api.match_by_name_address("스타벅스 광화문점", "서울 종로구 종로 10", db=sample) != []   # 주소가 같으면 같은 점포(이름 점수만 비슷)


def test_chain_other_branch_other_address_is_not_matched(sample):
    assert api.match_by_name_address("스타벅스 명동점", "서울 중구 명동8가길 26", db=sample) == []


@pytest.mark.parametrize("name,stripped", [
    ("왕비집 명동본점", "왕비집"), ("스타벅스 안국역점", "스타벅스"), ("왕비집", "왕비집"), ("본점", "본점"), ("왕비집 본점", "왕비집"),
])
def test_strip_branch_suffix(name, stripped):
    assert strip_branch_suffix(name) == stripped


# ---- 구글 링크 이름 속 주소 분리 ----

@pytest.mark.parametrize("text,expected", [
    ("서울특별시 중구 명동8가길 26 왕비집 명동본점", ("서울특별시 중구 명동8가길 26", "왕비집 명동본점")),
    ("서울 종로구 창덕궁1길 39 1층 라타르타", ("서울 종로구 창덕궁1길 39", "라타르타")),
    ("서울 종로구 계동길 17 지하1층 쿄와우동", ("서울 종로구 계동길 17", "쿄와우동")),
    ("서울숲 클라이밍", None),                    # 시·도로 시작하지 않는다
    ("서울 성동구 성수이로 100", None),           # 상호가 없다
    ("왕비집 명동본점", None),
])
def test_split_address_and_name(text, expected):
    assert split_address_and_name(text) == expected


def _google(name):
    from urllib.parse import quote
    return f"https://www.google.com/maps/place/{quote(name)}/data=!4m2!3m1!1s0x0:0x1"


def test_google_name_with_address_is_matched_by_hint(sample):
    r = api.parse_link(_google("서울특별시 중구 명동8가길 26 왕비집 명동본점"), db=sample)
    assert r.provider == "google" and r.matched_by == "hint" and [m.place_name for m in r.matches] == ["왕비집"]
    assert r.needs_search_query is False


def test_google_name_that_cannot_be_split_stays_a_name_hint(sample):
    r = api.parse_link(_google("왕비집 명동본점"), db=sample)
    assert r.matches == [] and r.matched_by is None and r.name_hint == "왕비집 명동본점"


def test_places_not_in_our_db_stay_empty(sample):
    for name, addr in [("우슬", "대전 중구 중앙로138번길 48"), ("강남면옥 정동점", "서울 중구 정동길 3"), ("오늘의집 북촌", "서울 종로구 북촌로 10")]:
        assert api.match_by_name_address(name, addr, db=sample) == []


# ---- 메모리 대역 ----

def test_fake_address_candidates():
    fake = FakePlaces(rows=[_Row("a", "법인명 카페", 37.5, 127.0, "카페", address="서울 종로구 창덕궁1길 39 1층"),
                            _Row("b", "다중 A", 37.5, 127.0, "카페", address="서울 중구 중앙로138번길 48"),
                            _Row("c", "다중 B", 37.5, 127.0, "카페", address="서울 중구 중앙로138번길 48")])
    assert [r.place_name for r in fake.match_address_candidates("서울 종로구 창덕궁1길 39")] == ["법인명 카페"]
    assert fake.match_address_candidates("서울 중구 중앙로138번길 48") == []

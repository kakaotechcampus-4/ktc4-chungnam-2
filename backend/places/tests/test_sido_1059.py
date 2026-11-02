"""주소·좌표의 시·도(#1059) — sido는 순수 함수, sido_at은 가장 가까운 자체 DB 장소 주소의 시·도."""

import uuid

import pytest

from places import api, core
from places.models import Place
from places.testing import FakePlaces, _Row


@pytest.mark.parametrize("address, expected", [
    ("서울특별시 성동구 성수이로 10", "서울"),
    ("서울 성동구 성수이로 10", "서울"),
    ("서울시 성동구 성수이로 10", "서울"),
    ("부산광역시 해운대구 해운대해변로 264 (우동)", "부산"),
    ("세종특별자치시 한누리대로 2130", "세종"),
    ("경기도 수원시 팔달구 효원로 1", "경기"),
    ("경기 광주시 오포읍 1", "경기"),                      # 경기도 광주시는 광주가 아니다
    ("강원특별자치도 춘천시 중앙로 1", "강원"),
    ("강원도 춘천시 중앙로 1", "강원"),
    ("충청남도 천안시 동남구 1", "충남"),
    ("전북특별자치도 전주시 완산구 1", "전북"),
    ("전라북도 전주시 완산구 1", "전북"),
    ("경상북도 경주시 1", "경북"),
    ("제주특별자치도 제주시 1", "제주"),
    ("제주도 제주시 1", "제주"),
    ("전남광주통합특별시 동구 금남로 1", "전남광주"),       # 2026 통합
    ("광주광역시 동구 금남로 1", "전남광주"),
    ("광주특별시 동구 금남로 1", "전남광주"),
    ("전라남도 여수시 1", "전남광주"),
    ("전남 여수시 1", "전남광주"),
])
def test_sido_normalizes_to_one_short_name(address, expected):
    assert core.sido(address) == expected
    assert api.sido(address) == expected


@pytest.mark.parametrize("address", [None, "", "   ", "성동구 성수이로 10", "수원시 팔달구 1", "어딘가 123", "도 1", "시 1"])
def test_sido_is_none_without_a_sido(address):
    assert core.sido(address) is None


def _place(db, lat, lng, address, status="open"):
    db.add(Place(source="permit", source_id=uuid.uuid4().hex, name="가게", category="음식점", status=status, address=address,
                 geom=f"SRID=4326;POINT({lng} {lat})"))
    db.flush()


def test_sido_at_uses_the_nearest_place_with_an_address(db_session):
    _place(db_session, 37.5445, 127.0561, None)                                       # 가장 가깝지만 주소 없음 → 다음 곳
    _place(db_session, 37.5446, 127.0561, "서울특별시 성동구 성수이로 10")
    _place(db_session, 37.5447, 127.0561, "부산광역시 해운대구 해운대해변로 264", status="closed")   # 폐업은 보지 않는다
    _place(db_session, 37.5500, 127.0561, "경기도 어딘가 1")
    assert api.sido_at(37.5445, 127.0561, db=db_session) == "서울"


def test_sido_at_is_none_when_nothing_is_near(db_session):
    _place(db_session, 37.5445, 127.0561, "서울특별시 성동구 성수이로 10")
    assert api.sido_at(35.1, 129.0, db=db_session) is None                            # 10km 안에 장소 없음


def test_fake_sido_at_follows_the_same_rule(monkeypatch):
    fake = FakePlaces()
    assert fake.sido_at(37.5445, 127.0561) is None                                    # 샘플은 주소가 없다 = 모름
    fake.rows.append(_Row("haeundae", "해운대 국밥", 35.1587, 129.1604, "음식점", address="부산광역시 해운대구 우동 1"))
    fake.install(monkeypatch)
    assert api.sido_at(35.1590, 129.1600) == "부산"
    assert api.sido("서울 성동구") == "서울"

"""상호명·주소로 자체 DB 짝 찾기(#946) — 순수 규칙, 메모리 대역, DB 후보 좁히기."""

import logging

import pytest
from sqlalchemy import func

from places import api, matching, repository
from places.matching import Candidate, hint_name_keys, pick_hint_match
from places.models import Place
from places.testing import FakePlaces, _Row


def _c(pid, name, address=None, category="카페"):
    return Candidate(pid, name, 37.5, 127.0, category, address=address)


# ---- 순수 규칙 ----

def test_unique_name_match_returns_the_one():
    assert [c.place_id for c in pick_hint_match("온도 커피 성수", None, [_c("a", "온도 커피 성수")])] == ["a"]


@pytest.mark.parametrize("category", ["음식점", "카페", "관광지"])
def test_any_own_category(category):
    assert pick_hint_match("서울숲", None, [_c("a", "서울숲", category=category)])


def test_unknown_category_is_ignored():
    assert pick_hint_match("호텔", None, [_c("a", "호텔", category="숙소")]) == []


def test_two_same_name_branches_without_address_is_ambiguous():
    cands = [_c("a", "스타벅스 성수점"), _c("b", "스타벅스 성수점")]
    assert pick_hint_match("스타벅스 성수점", None, cands) == []


def test_address_picks_the_right_branch():
    cands = [_c("a", "스타벅스 성수점", "서울 성동구 성수이로 100"), _c("b", "스타벅스 성수점", "서울 성동구 아차산로 5")]
    assert [c.place_id for c in pick_hint_match("스타벅스 성수점", "서울 성동구 성수이로 100", cands)] == ["a"]


def test_address_mismatch_returns_nothing():
    cands = [_c("a", "스타벅스 성수점", "서울 성동구 성수이로 200")]
    assert pick_hint_match("스타벅스 성수점", "서울 성동구 성수이로 100", cands) == []


def test_address_rescues_a_similar_name_only_when_it_agrees():
    cands = [_c("a", "성수칼국수집", "서울특별시 성동구 성수이로 100 (성수동2가)", "음식점")]
    assert pick_hint_match("성수 손칼국수 본점", "서울 성동구 성수이로 100", cands)
    assert pick_hint_match("성수 손칼국수 본점", None, cands) == []


def test_name_keys():
    assert hint_name_keys("온도 커피 (성수점)") == ("온도커피", ["온도", "온도커", "온도커피"])
    assert hint_name_keys("  !! ") == ("", [])


# ---- 메모리 대역(공개 함수와 같은 모양) ----

def test_fake_matches_and_refuses():
    fake = FakePlaces()
    got = fake.match_by_name_address("성수 칼국수", None)
    assert [r.place_name for r in got] == ["성수 칼국수"] and got[0].pinnable and got[0].place_id.startswith("own:")
    assert fake.match_by_name_address("없는 가게", None) == []
    assert fake.match_by_name_address("", None) == []


def test_fake_ambiguous_chain_is_empty():
    fake = FakePlaces(rows=[_Row("a", "체인 커피", 37.5, 127.0, "카페"), _Row("b", "체인 커피", 37.6, 127.1, "카페")])
    assert fake.match_by_name_address("체인 커피", None) == []


# ---- DB: 후보를 name_norm 인덱스 조건으로 좁힌다 ----

def _add(db, sid, name, category="카페", address=None, status="open"):
    db.add(Place(source="permit", source_id=sid, name=name, category=category, address=address, status=status,
                 geom=func.ST_SetSRID(func.ST_MakePoint(127.05, 37.54), 4326)))
    db.flush()


def test_db_candidates_by_name_prefix_and_leading_part(db_session):
    _add(db_session, "1", "온도 커피 성수")
    _add(db_session, "2", "온도 (본점)")            # 힌트의 앞부분 "온도"와 정확히 같다
    _add(db_session, "3", "다른 가게")
    _add(db_session, "4", "온도 커피 뚝섬", status="closed")
    names = sorted(c.name for c in repository.find_by_name_hint(db_session, "온도 커피"))
    assert names == ["온도 (본점)", "온도 커피 성수"]


def test_db_match_unique_and_ambiguous(db_session):
    _add(db_session, "1", "유일 식당", "음식점", "서울 성동구 성수이로 100")
    _add(db_session, "2", "체인 카페", address="서울 성동구 성수이로 1")
    _add(db_session, "3", "체인 카페", address="서울 성동구 아차산로 2")
    got = api.match_by_name_address("유일 식당", "서울특별시 성동구 성수이로 100", db=db_session)
    assert [r.place_name for r in got] == ["유일 식당"]
    assert api.match_by_name_address("체인 카페", None, db=db_session) == []
    assert [r.place_name for r in api.match_by_name_address("체인 카페", "서울 성동구 아차산로 2", db=db_session)] == ["체인 카페"]


def test_too_common_name_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(matching, "HINT_MAX_CANDIDATES", 2)
    for i in range(3):
        _add(db_session, str(i), f"흔한 카페 {i}번")
    assert repository.find_by_name_hint(db_session, "흔한 카페") == []


def test_name_and_address_are_not_logged(db_session, caplog):
    _add(db_session, "1", "비밀 식당", "음식점", "서울 성동구 성수이로 100")
    with caplog.at_level(logging.DEBUG):
        api.match_by_name_address("비밀 식당", "서울 성동구 성수이로 100", db=db_session)
    assert "비밀" not in caplog.text and "성수이로" not in caplog.text

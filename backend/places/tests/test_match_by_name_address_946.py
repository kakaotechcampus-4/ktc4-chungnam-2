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

ADDR = "서울 성동구 성수이로 100"
OTHER = "서울 성동구 아차산로 5"


def _ids(r):
    return [c.place_id for c in r]


def test_unique_name_and_same_address_matches():
    assert _ids(pick_hint_match("온도 커피 성수", ADDR, [_c("a", "온도 커피 성수", ADDR)])) == ["a"]


@pytest.mark.parametrize("category", ["음식점", "카페", "관광지"])
def test_any_own_category(category):
    assert pick_hint_match("서울숲", ADDR, [_c("a", "서울숲", ADDR, category)])


def test_unknown_category_is_ignored():
    assert pick_hint_match("호텔", ADDR, [_c("a", "호텔", ADDR, "숙소")]) == []


def test_no_input_address_never_matches_even_with_a_single_candidate():
    assert pick_hint_match("스타벅스", None, [_c("a", "스타벅스", ADDR)]) == []
    assert pick_hint_match("스타벅스", "  ", [_c("a", "스타벅스", ADDR)]) == []


def test_candidate_address_unknown_is_not_confirmed():
    assert pick_hint_match("스타벅스", ADDR, [_c("a", "스타벅스", None)]) == []
    assert pick_hint_match("스타벅스", ADDR, [_c("a", "스타벅스", "서울 성동구")]) == []   # 읽을 수 없는 주소


def test_address_picks_the_right_branch():
    cands = [_c("a", "스타벅스 성수점", ADDR), _c("b", "스타벅스 성수점", OTHER)]
    assert _ids(pick_hint_match("스타벅스 성수점", ADDR, cands)) == ["a"]


def test_address_mismatch_returns_nothing():
    assert pick_hint_match("스타벅스 성수점", ADDR, [_c("a", "스타벅스 성수점", "서울 성동구 성수이로 200")]) == []


def test_two_same_score_both_address_match_is_ambiguous():
    cands = [_c("a", "스타벅스 성수점", ADDR), _c("b", "스타벅스 성수점", ADDR)]
    assert pick_hint_match("스타벅스 성수점", ADDR, cands) == []


def test_same_score_address_match_vs_address_unknown_is_ambiguous():
    cands = [_c("a", "스타벅스 성수점", ADDR), _c("b", "스타벅스 성수점", None)]
    assert pick_hint_match("스타벅스 성수점", ADDR, cands) == []


def test_unknown_address_rival_with_higher_name_score_blocks_a_rescued_match():
    # A는 주소만 같고 이름이 모자란 구제 후보(0.5~0.8), B는 이름이 거의 같지만 주소를 모른다 → 근거 없이 A를 확정하지 않는다
    cands = [_c("a", "성수칼국수집", ADDR, "음식점"), _c("b", "성수 손칼국수 본점", None, "음식점")]
    assert pick_hint_match("성수 손칼국수 본점", ADDR, cands) == []


def test_strong_address_match_wins_over_clearly_lower_unknown_rival():
    cands = [_c("a", "스타벅스 성수점", ADDR), _c("b", "스타벅스 성수역점", None)]
    assert _ids(pick_hint_match("스타벅스 성수점", ADDR, cands)) == ["a"]   # B는 이름 점수가 한참 낮다


def test_rescued_address_match_alone_is_ok_and_needs_the_address():
    cands = [_c("a", "성수칼국수집", "서울특별시 성동구 성수이로 100 (성수동2가)", "음식점")]
    assert pick_hint_match("성수 손칼국수 본점", ADDR, cands)
    assert pick_hint_match("성수 손칼국수 본점", None, cands) == []


def test_name_keys():
    assert hint_name_keys("온도 커피 (성수점)") == ("온도커피", ["온도", "온도커", "온도커피"])
    assert hint_name_keys("  !! ") == ("", [])


# ---- 메모리 대역(공개 함수와 같은 모양) ----

def _fake(*rows):
    return FakePlaces(rows=[_Row(k, n, 37.5, 127.0, cat, address=a) for k, n, cat, a in rows])


def test_fake_matches_and_refuses():
    fake = _fake(("a", "성수 칼국수", "음식점", ADDR))
    got = fake.match_by_name_address("성수 칼국수", ADDR)
    assert [r.place_name for r in got] == ["성수 칼국수"] and got[0].pinnable and got[0].place_id.startswith("own:")
    assert fake.match_by_name_address("성수 칼국수", None) == []
    assert fake.match_by_name_address("없는 가게", ADDR) == []
    assert fake.match_by_name_address("", ADDR) == []


def test_fake_ambiguous_chain_is_empty():
    fake = _fake(("a", "체인 커피", "카페", ADDR), ("b", "체인 커피", "카페", ADDR))
    assert fake.match_by_name_address("체인 커피", ADDR) == []


# ---- DB: 후보를 name_norm 인덱스 조건으로 좁힌다 ----

def _add(db, sid, name, category="카페", address=None, status="open", lng=127.05):
    db.add(Place(source="permit", source_id=sid, name=name, category=category, address=address, status=status,
                 geom=func.ST_SetSRID(func.ST_MakePoint(lng, 37.54), 4326)))
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
    _add(db_session, "3", "체인 카페", address="서울 성동구 아차산로 2", lng=127.2)   # 다른 동네 지점 — 같은 자리면 핀 생성이 주소 없이 가를 수 없다(#815)
    got = api.match_by_name_address("유일 식당", "서울특별시 성동구 성수이로 100", db=db_session)
    assert [r.place_name for r in got] == ["유일 식당"]
    assert api.match_by_name_address("체인 카페", None, db=db_session) == []
    assert api.match_by_name_address("유일 식당", None, db=db_session) == []   # 주소가 없으면 하나뿐이어도 확정하지 않는다
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

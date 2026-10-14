"""주소 보조 매칭(#500)의 순수 함수 단위 테스트 — DB 없이 돈다."""

import pytest

from places.matching import Candidate, address_agreement, normalize_address, pick_match
from places.schemas import PlaceHint
from places.testing import FakePlaces, _Row


def _hint(name="스타벅스 성수점", address=None, category="카페", kakao_place_id=None):
    return PlaceHint(kakao_place_id, name, 37.5445, 127.0561, category, address)


def _cand(pid, name, address, dist=10.0, category="카페"):
    return Candidate(pid, name, 37.5445, 127.0561, category, distance_m=dist, address=address)


# ---- 표기 정리 ----

@pytest.mark.parametrize("text,key", [
    ("서울특별시 성동구 성수이로 100", ("road", "성수이로|100")),
    ("서울 성동구 성수이로 100 (성수동2가) 1층", ("road", "성수이로|100")),
    ("성수이로100", ("road", "성수이로|100")),
    ("서울 강남구 논현로 12길 5", ("road", "논현로12길|5")),
    ("서울 성동구 성수동2가 300-1", ("lot", "성수동2가|300-1")),
    ("서울 성동구 성수동 0300", ("lot", "성수동|300")),
])
def test_normalize_address(text, key):
    assert normalize_address(text) == key


def test_normalize_address_unreadable_is_none():
    assert normalize_address("서울 성동구") is None
    assert normalize_address("") is None


def test_address_agreement_cases():
    assert address_agreement("서울 성동구 성수이로 100", "서울특별시 성동구 성수이로 100 (성수동)") is True   # 표기 차이
    assert address_agreement("서울 성동구 성수이로 100", "서울 성동구 성수이로 102") is False
    assert address_agreement("서울 성동구 성수이로 100", "서울 성동구 성수동2가 300-1") is None   # 도로명 vs 지번 — 비교 불가
    assert address_agreement("서울 성동구 성수이로 100", None) is None
    assert address_agreement("서울 성동구 성수이로 100", "서울 성동구 성수이로 100-1") is None     # 본번만 같고 부번이 한쪽에 없다


# ---- pick_match ----

def test_address_match_rescues_similar_name():
    h = _hint("성수 손칼국수 본점", "서울 성동구 성수이로 100", category="음식점")
    c = [_cand("a", "성수칼국수집", "서울특별시 성동구 성수이로 100 (성수동2가)", category="음식점")]
    assert pick_match(_hint("성수 손칼국수 본점", category="음식점"), c) is None   # 주소 없이는 이름이 모자라 거절
    assert pick_match(h, c).place_id == "a"


def test_address_does_not_rescue_unrelated_name():
    cands = [_cand("a", "전혀 다른 가게", "서울 성동구 성수이로 100")]
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands) is None   # 같은 건물의 다른 가게


def test_address_mismatch_rejects_same_name_other_branch():
    cands = [_cand("a", "스타벅스 성수점", "서울 성동구 성수이로 200")]
    assert pick_match(_hint(), cands) is not None                                  # 주소 없으면 이름만으로 매칭(기존)
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands) is None     # 주소가 다르면 다른 지점


def test_address_resolves_same_name_ambiguity():
    cands = [_cand("a", "스타벅스 성수점", "서울 성동구 성수이로 200", dist=5.0),
             _cand("b", "스타벅스 성수점", "서울 성동구 성수이로 100", dist=12.0)]
    assert pick_match(_hint(), cands) is None                                      # 주소 없이는 모호 → 거절(기존 규칙 유지)
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands).place_id == "b"


def test_ambiguous_when_both_share_address():
    cands = [_cand("a", "스타벅스 성수점", "서울 성동구 성수이로 100", dist=5.0),
             _cand("b", "스타벅스 성수점", "서울 성동구 성수이로 100", dist=12.0)]
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands) is None


def test_strong_name_candidate_wins_over_rescued():
    cands = [_cand("weak", "성수 카페거리", "서울 성동구 성수이로 100"),
             _cand("strong", "스타벅스 성수점", None)]
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands).place_id == "strong"


def test_uncomparable_address_falls_back_to_name_only():
    cands = [_cand("a", "스타벅스 성수점", "서울 성동구 성수동2가 300-1")]
    assert pick_match(_hint(address="서울 성동구 성수이로 100"), cands).place_id == "a"   # 도로명 vs 지번 — 판단 불가라 이름 규칙 그대로


def test_kakao_id_match_ignores_address():
    c = Candidate("a", "전혀 다른 이름", 37.0, 127.0, "카페", kakao_place_id="k1", address="서울 성동구 성수이로 200")
    assert pick_match(_hint(address="서울 성동구 성수이로 100", kakao_place_id="k1"), [c]).place_id == "a"


# ---- 메모리 대역(FakePlaces)도 같은 규칙 ----

def test_fake_places_uses_same_address_rule():
    fake = FakePlaces(rows=[
        _Row("a", "스타벅스 성수점", 37.5445, 127.0561, "카페", address="서울 성동구 성수이로 200"),
        _Row("b", "스타벅스 성수점", 37.5446, 127.0562, "카페", address="서울 성동구 성수이로 100"),
    ])
    assert fake.match_place(_hint()) is None
    assert fake.match_place(_hint(address="서울특별시 성동구 성수이로 100")).place_id == fake.place_id("b")

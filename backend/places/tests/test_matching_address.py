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


# ---- 분기 도로(번길·안길·N길·N가길)는 도로명의 일부다(#1019) ----

@pytest.mark.parametrize("text,key", [
    ("서울 성동구 아차산로17번길 4", ("road", "아차산로17번길|4")),
    ("서울 성동구 아차산로 17번길 4", ("road", "아차산로17번길|4")),
    ("서울 성동구 아차산로 17안길 4", ("road", "아차산로17안길|4")),
    ("서울 강남구 테헤란로14길 5", ("road", "테헤란로14길|5")),
    ("서울 성동구 연무장5길 9", ("road", "연무장5길|9")),
    ("서울 성동구 연무장5가길 7", ("road", "연무장5가길|7")),
    ("서울 성동구 연무장 5가길 7", ("road", "연무장5가길|7")),
    ("서울 영등포구 수유로12나길 3", ("road", "수유로12나길|3")),
    ("서울 성동구 아차산로17번길 4-1", ("road", "아차산로17번길|4-1")),
    ("서울 성동구 성수이로 100", ("road", "성수이로|100")),   # 기존 표기는 그대로
])
def test_branch_roads_are_part_of_the_street(text, key):
    assert normalize_address(text) == key


@pytest.mark.parametrize("a,b,expected", [
    ("서울 성동구 아차산로17번길 4", "서울 성동구 아차산로17번길 99", False),     # 같은 번길의 다른 건물 — 예전엔 True였다
    ("서울 성동구 아차산로17번길 4", "서울특별시 성동구 아차산로 17번길 4 (성수동)", True),
    ("서울 성동구 아차산로17번길 4", "서울 성동구 아차산로18번길 4", False),       # 다른 번길
    ("서울 성동구 아차산로 17안길 4", "서울 성동구 아차산로17안길 5", False),
    ("서울 성동구 아차산로 17안길 4", "서울 성동구 아차산로17번길 4", False),      # 안길과 번길은 다른 길
    ("서울 강남구 테헤란로14길 5", "서울 강남구 테헤란로14길 6", False),
    ("서울 강남구 테헤란로14길 5", "서울 강남구 테헤란로 14길 5", True),
    ("서울 성동구 연무장5길 9", "서울 성동구 연무장5길 10", False),
    ("서울 성동구 연무장5가길 7", "서울 성동구 연무장 5가길 7", True),
    ("서울 성동구 연무장5가길 7", "서울 성동구 연무장6가길 7", False),             # 예전엔 둘 다 "가길|7"
    ("서울 영등포구 수유로12나길 3", "서울 영등포구 수유로12나길 4", False),
    ("서울 성동구 아차산로17번길 4", "서울 성동구 아차산로 4", False),             # 번길 위 4번지와 큰길 4번지
])
def test_address_agreement_on_branch_roads(a, b, expected):
    assert address_agreement(a, b) is expected


# ---- 백트래킹으로 되살아나던 오탐(#1019 검수 반례) — 도로명은 단계로 읽는다 ----

@pytest.mark.parametrize("text,key", [
    ("서울 성동구 아차산로17번길 지하 4", ("road", "아차산로17번길|4")),
    ("경북 구미시 1공단로 10", ("road", "1공단로|10")),
    ("경북 구미시 공단동 1공단로 10", ("road", "1공단로|10")),
    ("서울 성동구 성수이로 100 한길빌딩 3층", ("road", "성수이로|100")),
    ("서울 성동구 아차산로 17", ("road", "아차산로|17")),
    ("서울 중구 을지로3가 100", ("lot", "을지로3가|100")),
    ("서울 종로구 종로1가 24", ("lot", "종로1가|24")),
])
def test_staged_road_parse(text, key):
    assert normalize_address(text) == key


@pytest.mark.parametrize("text", [
    "서울 성동구 아차산로17번길",            # 건물번호 없음 — 17은 번길 번호지 건물번호가 아니다
    "서울 성동구 아차산로17 번길",
    "서울 성동구 아차산로17번길 101호",      # 호수는 건물번호가 아니다
])
def test_branch_number_is_never_read_as_the_building_number(text):
    assert normalize_address(text) is None


@pytest.mark.parametrize("a,b,expected", [
    ("서울 성동구 아차산로17번길 4", "서울 성동구 아차산로17번길 99", False),
    ("서울 성동구 아차산로17번길 지하 4", "서울 성동구 아차산로17번길 지하 99", False),
    ("서울 성동구 아차산로17번길 지하 4", "서울 성동구 아차산로 17", False),
    ("서울 성동구 아차산로17번길", "서울 성동구 아차산로 17", None),               # 건물번호를 알 수 없다
    ("서울 성동구 아차산로17 번길 4", "서울 성동구 아차산로17번길 4", None),   # 공백 낀 분기 표기는 읽지 않는다(3차 결정)
    ("경북 구미시 1공단로 10", "경북 구미시 공단동 1공단로 10", True),
    ("서울 성동구 성수이로 100 한길빌딩 3층", "서울 성동구 성수이로 100", True),
])
def test_agreement_on_the_agy_counterexamples(a, b, expected):
    assert address_agreement(a, b) is expected


# ---- 2차 검수 반례(#1019): 한글+숫자+로 회귀, 지번 fallback 오탐, 분기 번호 앞 공백, 산 번지 ----

@pytest.mark.parametrize("text,key", [
    ("경기 평택시 중앙1로 5", ("road", "중앙1로|5")),
    ("부산 해운대구 센텀1로 25", ("road", "센텀1로|25")),
    ("부산 해운대구 마린시티1로 7", ("road", "마린시티1로|7")),
    ("경기 평택시 중앙1로 12번길 5", ("road", "중앙1로12번길|5")),
    ("서울 성동구 성수동2가 300-1", ("lot", "성수동2가|300-1")),
])
def test_review2_keys(text, key):
    assert normalize_address(text) == key


@pytest.mark.parametrize("text", [
    "서울 성동구 17번길 4",                      # 성동구는 도로명이 아니다, 번길 단독도 도로명이 아니다
    "경북 구미시 공단동 1공단로 101호",           # 호수가 지번(공단동 1)으로 읽히지 않는다
    "서울 종로구 인사동10길 101호",
    "서울 중구 을지로3가 101호",
    "서울 성동구 아차산로17번길 가동 101호",
    "서울 성동구 성수동2가 산 300-1",             # 산 번지는 일반 번지와 다른 필지라 읽지 않는다
])
def test_review2_unreadable_is_none(text):
    assert normalize_address(text) is None


@pytest.mark.parametrize("a,b,expected", [
    ("경기 평택시 중앙1로 5", "경기 평택시 중앙1로 99", False),
    ("부산 해운대구 상동1로 10", "부산 해운대구 상동1로 99", False),                    # 예전엔 False였는데 지번 fallback이 True로 만들었다
    ("경기 평택시 중앙1로 12번길 5", "경기 안산시 공단1로 12번길 5", False),            # 다른 도로
    ("서울 성동구 성수이로 100 한길빌딩 3층", "서울 성동구 성수이로 100", True),
    ("서울 성동구 성수이로 100 꽃길", "서울 성동구 성수이로 100", True),             # 꽃길은 가지번호가 아니라 분기가 아니다
])
def test_review2_agreement(a, b, expected):
    assert address_agreement(a, b) is expected


# ---- 3차 검수(#1019): 범위를 좁혀 안전한 쪽(None)으로 — 공백 낀 분기 표기는 읽지 않고, 분기 한글은 가지번호뿐이다 ----

@pytest.mark.parametrize("text,key", [
    ("서울 동작구 상도13가길 5", ("road", "상도13가길|5")),
    ("인천 연수구 송도1길 5", ("road", "송도1길|5")),
    ("서울 성동구 성수이로 100 꽃길 2", ("road", "성수이로|100")),
    ("서울 성동구 성수이로 100 한길 2", ("road", "성수이로|100")),
    ("서울 강남구 테헤란로14길 5 한길 2", ("road", "테헤란로14길|5")),
    ("서울 성동구 성수동 100 꽃길 2", ("lot", "성수동|100")),
])
def test_round3_keys(text, key):
    assert normalize_address(text) == key


@pytest.mark.parametrize("text", [
    "서울 성동구 아차산로 17 번길 4",        # 접미사 앞 공백 — 번길|4가 head로 잡히지 않는다
    "서울 성동구 17 번길 4",
    "서울 성동구 아차산로 5 가길 7",
    "서울 강남구 테헤란로 14 길 5",
    "서울 종로구 인사동 10 길 101호",         # 지번(인사동 10)으로 낚이지 않는다
    "서울 성동구 성수동2가 17 번길 101호",
    "서울 성동구 아차산로17번길 1F",          # 영문이 이어지면 건물번호가 아니다
    "인천 연수구 송도 1길 5",                 # 공백 표기는 지원하지 않는다
])
def test_round3_unreadable_is_none(text):
    assert normalize_address(text) is None


@pytest.mark.parametrize("a,b,expected", [
    ("서울 성동구 아차산로 5 가길 7", "서울 성동구 아차산로 6 가길 7", None),         # 예전엔 True
    ("서울 성동구 성수이로 100 꽃길 2", "서울 성동구 성수이로 100", True),
    ("서울 강남구 테헤란로14길 5 한길 2", "서울 강남구 테헤란로14길 5", True),
    ("서울 동작구 상도13가길 5", "서울 동작구 상도13가길 6", False),
])
def test_round3_agreement(a, b, expected):
    assert address_agreement(a, b) is expected

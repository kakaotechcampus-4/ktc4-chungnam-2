"""자체 장소 DB 공개 함수 — 시그니처 고정(FakePlaces ≡ api)과 FakePlaces·매칭 규칙 동작."""

import inspect

import pytest

from places import api, matching
from places.matching import Candidate, name_score, normalize_name, pick_match
from places.schemas import Area, FactLabel, PlaceHint, PlaceInfo, PlaceMatch, PlaceRef
from places.testing import FakePlaces, sample_id

FUNCS = ("match_place", "record_kakao_match", "pinnable_flags", "get_places", "search_nearby_own", "get_facts")


@pytest.fixture()
def fake():
    return FakePlaces()


def _hint(name="성수 칼국수", lat=37.5445, lng=127.0561, category="음식점", kakao_place_id="k1"):
    return PlaceHint(kakao_place_id=kakao_place_id, name=name, lat=lat, lng=lng, category=category)


# ---- 시그니처 ----

@pytest.mark.parametrize("name", FUNCS)
def test_fake_signatures_match_api(name):
    def shape(fn):
        sig = inspect.signature(fn)
        return [(p.name, str(p.annotation)) for p in sig.parameters.values() if p.name != "self"], str(sig.return_annotation)

    assert shape(getattr(FakePlaces, name)) == shape(getattr(api, name))


def test_dataclasses_are_frozen():
    for obj in (_hint(), PlaceMatch("p", "n", 1, 2, "음식점"), PlaceInfo("p", "n", 1, 2, "음식점"),
                PlaceRef("p", 1, 2), FactLabel("quiet", True, "known")):
        with pytest.raises(Exception):
            obj.lat = 0   # FrozenInstanceError


def test_install_replaces_api_functions(fake, monkeypatch):
    fake.install(monkeypatch)
    assert api.match_place(_hint()).name == "성수 칼국수"


# ---- match_place ----

def test_match_exact_name_within_radius(fake):
    m = fake.match_place(_hint())
    assert m == PlaceMatch(sample_id("seongsu-kalguksu"), "성수 칼국수", 37.5445, 127.0561, "음식점")


def test_match_ignores_spacing_and_branch_suffix_in_parentheses(fake):
    assert fake.match_place(_hint(name="성수칼국수 (본점)")).place_id == sample_id("seongsu-kalguksu")


def test_match_uses_own_name_and_coords_not_the_hints(fake):
    m = fake.match_place(_hint(name="성수칼국수", lat=37.5447, lng=127.0563))
    assert (m.name, m.lat, m.lng) == ("성수 칼국수", 37.5445, 127.0561)   # 힌트 좌표가 아니라 자체 DB 값


def test_match_none_when_category_differs(fake):
    assert fake.match_place(_hint(category="카페")) is None


def test_match_none_when_too_far(fake):
    assert fake.match_place(_hint(lat=37.5445 + 0.004)) is None   # 약 440m


def test_match_none_when_name_differs(fake):
    assert fake.match_place(_hint(name="완전히 다른 가게")) is None


def test_match_skips_closed_places(fake):
    assert fake.match_place(_hint(name="종로 옛날국수", lat=37.5704, lng=126.9920)) is None


def test_match_none_for_lodging_and_etc(fake):
    assert fake.match_place(_hint(category="숙소")) is None
    assert fake.match_place(_hint(category="기타")) is None


def test_match_ambiguous_same_name_nearby_is_none():
    cands = [Candidate("a", "스타벅스 성수점", 37.5000, 127.0000, "카페"),
             Candidate("b", "스타벅스 성수점", 37.5001, 127.0000, "카페")]   # 11m 차
    assert pick_match(_hint("스타벅스 성수점", 37.5000, 127.0000, "카페"), cands) is None


def test_match_same_name_picks_clearly_nearer_one():
    cands = [Candidate("far", "스타벅스 성수점", 37.5020, 127.0000, "카페"),     # 222m
             Candidate("near", "스타벅스 성수점", 37.5001, 127.0000, "카페")]    # 11m
    assert pick_match(_hint("스타벅스 성수점", 37.5000, 127.0000, "카페"), cands).place_id == "near"


def test_match_by_previously_recorded_kakao_id_even_if_name_differs(fake):
    fake.record_kakao_match(sample_id("seongsu-kalguksu"), "k-777", "http://place.map.kakao.com/777")
    m = fake.match_place(_hint(name="이름이 달리 적힌 가게", kakao_place_id="k-777"))
    assert m.place_id == sample_id("seongsu-kalguksu")


def test_kakao_id_shortcut_still_requires_same_category(fake):
    fake.record_kakao_match(sample_id("seongsu-kalguksu"), "k-777", "u")
    assert fake.match_place(_hint(name="x", kakao_place_id="k-777", category="카페")) is None


def test_rule_constants():
    assert matching.MAX_CANDIDATES == 20 and matching.MAX_RADIUS_M == 300


# ---- pinnable_flags / record_kakao_match / get_places ----

def test_pinnable_flags_follow_match_and_do_not_record(fake):
    flags = fake.pinnable_flags([_hint(), _hint(name="없는 가게"), _hint(category="숙소")])
    assert flags == [True, False, False]
    assert fake.get_places([sample_id("seongsu-kalguksu")])[sample_id("seongsu-kalguksu")].kakao_place_url is None


def test_record_kakao_match_stores_only_id_and_url_and_keeps_the_first(fake):
    pid = sample_id("seongsu-kalguksu")
    fake.record_kakao_match(pid, "k1", "http://p/1")
    fake.record_kakao_match(pid, "k2", "http://p/2")
    assert fake.get_places([pid])[pid].kakao_place_url == "http://p/1"   # 첫 값 유지(#248)


def test_record_kakao_match_unknown_place_raises(fake):
    with pytest.raises(KeyError):
        fake.record_kakao_match("nope", "k", "u")


def test_get_places_batch_drops_unknown_ids(fake):
    a, b = sample_id("seoul-forest"), sample_id("gyeongbok")
    got = fake.get_places([a, "missing", b])
    assert set(got) == {a, b} and got[a].category == "관광지" and got[a].name == "서울숲"


# ---- search_nearby_own ----

def test_search_nearby_own_returns_open_places_of_category_within_any_area(fake):
    refs = fake.search_nearby_own("음식점", [Area(37.5445, 127.0561, 500)])
    assert {r.place_id for r in refs} == {sample_id("seongsu-kalguksu"), sample_id("seongsu-bunsik")}
    assert all(isinstance(r, PlaceRef) for r in refs)


def test_search_nearby_own_excludes_closed_and_other_categories(fake):
    assert fake.search_nearby_own("음식점", [Area(37.5704, 126.9920, 500)]) == []   # 폐업 점포 한 곳뿐
    assert fake.search_nearby_own("카페", [Area(37.5445, 127.0561, 300)])[0].place_id == sample_id("seongsu-cafe-a")


def test_search_nearby_own_has_no_lodging_or_etc(fake):
    area = [Area(37.5445, 127.0561, 5000)]
    assert fake.search_nearby_own("숙소", area) == [] and fake.search_nearby_own("기타", area) == []


def test_search_nearby_own_multiple_areas_is_union(fake):
    refs = fake.search_nearby_own("관광지", [Area(37.5444, 127.0374, 300), Area(37.5796, 126.9770, 300)])
    assert {r.place_id for r in refs} == {sample_id("seoul-forest"), sample_id("gyeongbok")}


# ---- get_facts ----

def test_get_facts_passes_labels_through_including_unknown(fake):
    labels = fake.get_facts([sample_id("seongsu-kalguksu")])[sample_id("seongsu-kalguksu")]
    by_key = {l.fact_key: l for l in labels}
    assert by_key["contains_shellfish"] == FactLabel("contains_shellfish", True, "known")
    assert by_key["oily_focused"].confidence == "unknown" and by_key["oily_focused"].value is None


def test_get_facts_without_labels_is_empty_list_per_requested_id(fake):
    pid = sample_id("gyeongbok")
    assert fake.get_facts([pid, "missing"]) == {pid: [], "missing": []}


# ---- 이름 매칭 규칙 ----

def test_normalize_name_strips_parentheses_spaces_and_symbols():
    assert normalize_name("성수 칼국수 (본점)") == "성수칼국수"
    assert normalize_name("A&B Cafe!") == "abcafe"
    assert normalize_name("  ") == ""


def test_name_score_levels():
    assert name_score("성수 칼국수", "성수칼국수") == 1.0
    assert name_score("스타벅스", "스타벅스 성수점") >= matching.NAME_MIN_SCORE
    assert name_score("카페", "성수동 카페거리 맛집") < matching.NAME_MIN_SCORE
    assert name_score("성수 칼국수", "홍대 라멘") < matching.NAME_MIN_SCORE
    assert name_score("", "x") == 0.0

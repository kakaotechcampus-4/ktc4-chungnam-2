"""선택 규칙 순수 함수(docs/ads.md 5절, 11절 1·2·3·5·6·8번의 순수 부분). DB 없이 돈다."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from ads import core
from ads.constants import AD_SLOTS
from common import categories

NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)


def ad(n: int, *, place: str | None = None, start=NOW - timedelta(days=1), end=NOW + timedelta(days=1),
       active=True) -> core.ActiveAd:
    return core.ActiveAd(f"ad{n}", place or f"p{n}", start, end, active)


# ---------------------------------------------------------------- 1. 기간과 active

def test_running_keeps_only_active_ads_inside_the_period():
    inside = ad(1)
    starts_now = ad(2, start=NOW)                          # starts_at <= now
    ends_now = ad(3, end=NOW)                              # ends_at 시각은 포함하지 않는다
    not_yet = ad(4, start=NOW + timedelta(seconds=1))
    inactive = ad(5, active=False)

    assert core.running([inside, starts_now, ends_now, not_yet, inactive], NOW) == [inside, starts_now]


# ---------------------------------------------------------------- 2·3. 빼기와 개수

@pytest.mark.parametrize("n, expected", [(0, 0), (1, 1), (2, 2), (3, 2), (6, 2)])
def test_choose_returns_up_to_slots(n, expected):
    ads = [ad(i) for i in range(n)]
    chosen = core.choose(ads, place_ids={a.place_id for a in ads}, excluded_place_ids=set(), rng=random.Random(1))

    assert len(chosen) == expected == min(n, AD_SLOTS)
    assert len({a.ad_id for a in chosen}) == expected


def test_choose_does_not_fill_from_places_outside_the_filter():
    """places.api가 거른(open, 카테고리, 반경) 장소에 없는 광고로 칸을 채우지 않는다."""
    ads = [ad(1), ad(2), ad(3)]

    chosen = core.choose(ads, place_ids={"p1"}, excluded_place_ids=set(), rng=random.Random(1))

    assert [a.ad_id for a in chosen] == ["ad1"]


def test_choose_drops_places_in_the_latest_recommendation():
    ads = [ad(1), ad(2), ad(3)]

    chosen = core.choose(ads, place_ids={"p1", "p2", "p3"}, excluded_place_ids={"p1", "p3"}, rng=random.Random(1))

    assert [a.ad_id for a in chosen] == ["ad2"]


# ---------------------------------------------------------------- 5. 시드 주입

def test_same_seed_gives_same_choice_regardless_of_input_order():
    ads = [ad(i) for i in range(10)]
    ids = {a.place_id for a in ads}

    first = core.choose(ads, place_ids=ids, excluded_place_ids=set(), rng=random.Random(42))
    again = core.choose(list(reversed(ads)), place_ids=ids, excluded_place_ids=set(), rng=random.Random(42))

    assert first == again


def test_choice_is_spread_over_all_candidates():
    """균등 랜덤 — 시드를 바꿔 가며 뽑으면 후보 모두가 한 번 이상 나온다."""
    ads = [ad(i) for i in range(5)]
    ids = {a.place_id for a in ads}
    seen = {a.ad_id for seed in range(200)
            for a in core.choose(ads, place_ids=ids, excluded_place_ids=set(), rng=random.Random(seed))}

    assert seen == {a.ad_id for a in ads}


# ---------------------------------------------------------------- 6. 카테고리

def test_request_categories_without_category_is_every_recommendable_category():
    assert core.request_categories(None) == categories.recommendable()
    assert core.request_categories("카페") == ("카페",)


# ---------------------------------------------------------------- on_map, 집계 날짜, 응답 모양

def test_on_map_by_db_pin_place_or_live_pin_kakao_id():
    place = {"id": "p1", "kakao_place_id": "kakao:9"}

    assert core.on_map(place, db_place_ids={"p1"}, live_kakao_ids=set()) is True
    assert core.on_map(place, db_place_ids=set(), live_kakao_ids={"kakao:9"}) is True
    assert core.on_map(place, db_place_ids={"p2"}, live_kakao_ids={"kakao:8"}) is False
    assert core.on_map({"id": "p1", "kakao_place_id": None}, db_place_ids=set(), live_kakao_ids={None}) is False


def test_stat_date_cuts_at_seoul_midnight():
    assert core.stat_date(datetime(2026, 11, 1, 14, 59, tzinfo=timezone.utc)).isoformat() == "2026-11-01"
    assert core.stat_date(datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)).isoformat() == "2026-11-02"   # 서울 0시


def test_to_item_has_only_the_contract_fields():
    place = {"id": "p1", "name": "가" * 120, "category": "카페", "address": None, "lat": 37.5, "lng": 127.0,
             "kakao_place_id": "kakao:1", "kakao_place_url": "https://place.map.kakao.com/1"}

    item = core.to_item(ad(1), place, on_map=False)

    assert set(item) == {"ad_id", "place", "on_map"}
    assert set(item["place"]) == {"place_id", "name", "category", "address", "lat", "lng", "place_url"}
    assert len(item["place"]["name"]) == 100
    assert item["place"]["place_url"] == "https://place.map.kakao.com/1"

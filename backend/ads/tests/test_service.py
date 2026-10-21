"""광고 조회와 클릭 기록 — 실제 places, recommend, pins 데이터 위에서(docs/ads.md 11절 1·2·4·6·7·8·9·12·16번).
db_session(롤백)만 쓴다."""

import random
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from ads import service
from ads.models import AdDailyStat
from ads.tests.conftest import NOW, SEONGSU
from common.errors import AppError
from places.models import Place

BUSAN = (35.1796, 129.0756)


def list_ads(world, map_id, *, user="u1", category="카페", now=NOW, seed=7):
    return service.list_ads(world.db, map_id=map_id, user_id=world.uid(user), category=category, center=SEONGSU,
                            now=now, rng=random.Random(seed))


def ad_ids(items) -> set[str]:
    return {i["ad_id"] for i in items}


# ---------------------------------------------------------------- 1. 후보에서 빠지는 광고

def test_ads_outside_period_inactive_closed_other_category_or_far_are_not_candidates(world):
    map_id = world.map()
    shown = world.ad(world.place("온도 커피"))
    world.ad(world.place("지난 광고"), starts_at=NOW - timedelta(days=10), ends_at=NOW - timedelta(days=1))
    world.ad(world.place("아직 안 시작"), starts_at=NOW + timedelta(hours=1), ends_at=NOW + timedelta(days=1))
    world.ad(world.place("내린 광고"), active=False)
    world.ad(world.place("폐업 카페", status="closed"))
    world.ad(world.place("칼국수집", category="음식점"))
    world.ad(world.place("부산 카페", lat=BUSAN[0], lng=BUSAN[1]))
    world.ad(world.place("6km 밖 카페", lat=SEONGSU[0] + 0.054))   # 위도 0.054도 ≈ 6km

    for seed in range(10):
        assert ad_ids(list_ads(world, map_id, seed=seed)) == {shown}


def test_ad_whose_place_row_is_missing_is_not_a_candidate(world):
    """FK가 없어 장소가 정리되면 광고 행만 남는다 — 후보에서 자연히 빠진다(명세 6절)."""
    map_id = world.map()
    world.ad(str(uuid.uuid4()))
    world.ad("not-a-uuid")

    assert list_ads(world, map_id) == []


# ---------------------------------------------------------------- 2. 요청자의 최신 추천 결과

def test_places_in_my_latest_run_are_dropped_but_other_members_runs_are_not(world):
    map_id = world.map()
    mine, theirs, old = world.place("내 추천 카페"), world.place("남의 추천 카페"), world.place("지난 추천 카페")
    ads = {pid: world.ad(pid) for pid in (mine, theirs, old)}
    world.run(map_id, by="u1", place_ids=[old], created_at=NOW - timedelta(days=1))
    world.run(map_id, by="u1", place_ids=[mine])                 # 최신 run
    world.run(map_id, by="u2", place_ids=[theirs, old])          # 다른 구성원 run은 보지 않는다

    for seed in range(10):
        assert ad_ids(list_ads(world, map_id, seed=seed)) == {ads[theirs], ads[old]}


def test_without_category_the_latest_run_of_every_category_is_dropped(world):
    map_id = world.map()
    cafe, food, sight = world.place("카페"), world.place("식당", category="음식점"), world.place("공원", category="관광지")
    keep = world.ad(sight)
    world.ad(cafe)
    world.ad(food)
    world.run(map_id, by="u1", category="카페", place_ids=[cafe])
    world.run(map_id, by="u1", category="음식점", place_ids=[food])

    assert ad_ids(list_ads(world, map_id, category=None)) == {keep}


# ---------------------------------------------------------------- 3. 개수, 반경 밖으로 채우지 않음

def test_at_most_two_and_never_filled_from_outside_the_radius(world):
    map_id = world.map()
    near = world.ad(world.place("가까운 카페"))
    world.ad(world.place("부산 카페 1", lat=BUSAN[0], lng=BUSAN[1]))
    world.ad(world.place("부산 카페 2", lat=BUSAN[0], lng=BUSAN[1]))

    assert ad_ids(list_ads(world, map_id)) == {near}

    for i in range(3):
        world.ad(world.place(f"성수 카페 {i}"))
    assert len(list_ads(world, map_id)) == 2


# ---------------------------------------------------------------- 4. 반응과 실격 필터를 거치지 않음

def test_place_the_group_opposed_or_that_fails_a_condition_stays_a_candidate(world):
    map_id = world.map()
    place = world.place("시끄러운 카페", kakao_place_id="kakao:77")
    world.fact(place, "quiet", False)                 # "조용한 곳" 실격 조건이라면 걸리는 장소
    ad_id = world.ad(place)
    pin = world.pin(map_id, place)
    world.against(pin, "u1")
    world.against(pin, "u2")

    items = list_ads(world, map_id)

    assert ad_ids(items) == {ad_id}
    assert items[0]["on_map"] is True


# ---------------------------------------------------------------- 6. 카테고리 없음

def test_without_category_ads_come_from_every_recommendable_category(world):
    map_id = world.map()
    ids = {world.ad(world.place("카페")), world.ad(world.place("식당", category="음식점")),
           world.ad(world.place("공원", category="관광지"))}

    seen = set()
    for seed in range(30):
        items = list_ads(world, map_id, category=None, seed=seed)
        assert len(items) == 2
        seen |= ad_ids(items)
    assert seen == ids


# ---------------------------------------------------------------- 7·8. 노출 집계

def test_each_served_ad_gets_one_served_count_and_unserved_ads_none(world):
    map_id = world.map()
    ads = [world.ad(world.place(f"카페 {i}")) for i in range(3)]

    served = ad_ids(list_ads(world, map_id))

    today = NOW.date()
    assert len(served) == 2
    for ad_id in ads:
        assert world.stats(ad_id) == ({today: (1, 0)} if ad_id in served else {})


def test_same_day_reuses_the_row_and_a_new_seoul_day_makes_a_new_row(world):
    map_id = world.map()
    ad_id = world.ad(world.place("카페"))
    before_midnight = NOW.replace(hour=14, minute=59)   # 서울 23:59
    after_midnight = NOW.replace(hour=15, minute=0)     # 서울 다음 날 0:00

    list_ads(world, map_id, now=before_midnight)
    list_ads(world, map_id, now=before_midnight)
    list_ads(world, map_id, now=after_midnight)

    day = before_midnight.date()
    assert world.stats(ad_id) == {day: (2, 0), day + timedelta(days=1): (1, 0)}


def test_nothing_is_counted_when_no_ad_is_served(world):
    map_id = world.map()
    world.ad(world.place("부산 카페", lat=BUSAN[0], lng=BUSAN[1]))

    assert list_ads(world, map_id) == []
    assert world.db.execute(select(sa.func.count()).select_from(AdDailyStat)).scalar_one() == 0


# ---------------------------------------------------------------- 9. on_map

def test_on_map_follows_db_pins_and_live_pins(world):
    map_id = world.map()
    place = world.place("카페", kakao_place_id="kakao:123", kakao_place_url="https://place.map.kakao.com/123")
    world.ad(place)

    assert list_ads(world, map_id)[0]["on_map"] is False

    pin = world.pin(map_id, place)
    assert list_ads(world, map_id)[0]["on_map"] is True

    world.delete_pin(pin)
    assert list_ads(world, map_id)[0]["on_map"] is False

    world.live_pin(map_id, "kakao:123")
    assert list_ads(world, map_id)[0]["on_map"] is True


def test_pin_on_another_map_does_not_count(world):
    map_id, other = world.map(), world.map()
    place = world.place("카페")
    world.ad(place)
    world.pin(other, place)

    assert list_ads(world, map_id)[0]["on_map"] is False


# ---------------------------------------------------------------- 응답 값은 places 행에서

def test_item_values_come_from_the_places_row(world):
    map_id = world.map()
    place = world.place("온도 커피 성수", address="서울 성동구 성수이로 1", kakao_place_id="kakao:5",
                        kakao_place_url="https://place.map.kakao.com/5")
    ad_id = world.ad(place, memo="비밀 계약 메모")

    [item] = list_ads(world, map_id)

    assert item["ad_id"] == ad_id
    assert item["place"] == {"place_id": place, "name": "온도 커피 성수", "category": "카페",
                             "address": "서울 성동구 성수이로 1", "lat": pytest.approx(SEONGSU[0]),
                             "lng": pytest.approx(SEONGSU[1]), "place_url": "https://place.map.kakao.com/5"}
    assert "비밀 계약 메모" not in repr(item)


# ---------------------------------------------------------------- 클릭 기록

def test_click_counts_even_after_the_ad_ended_or_was_taken_down(world):
    ended = world.ad(world.place("끝난 광고"), starts_at=NOW - timedelta(days=9), ends_at=NOW - timedelta(days=1))
    down = world.ad(world.place("내린 광고"), active=False)

    for ad_id in (ended, down, ended):
        service.record_click(world.db, ad_id=ad_id, now=NOW)

    assert world.stats(ended) == {NOW.date(): (0, 2)}
    assert world.stats(down) == {NOW.date(): (0, 1)}


def test_click_on_served_ad_shares_the_day_row(world):
    map_id = world.map()
    ad_id = world.ad(world.place("카페"))
    list_ads(world, map_id)

    service.record_click(world.db, ad_id=ad_id, now=NOW)

    assert world.stats(ad_id) == {NOW.date(): (1, 1)}


@pytest.mark.parametrize("ad_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_click_on_missing_ad_is_not_found(world, ad_id):
    with pytest.raises(AppError) as exc:
        service.record_click(world.db, ad_id=ad_id, now=NOW)
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------- 12·16. 경계

def test_stats_table_has_no_user_or_map_column(db_session):
    columns = {c["name"] for c in sa.inspect(db_session.connection()).get_columns("ad_daily_stats")}
    assert columns == {"ad_id", "stat_date", "served_count", "click_count"}


def test_serving_ads_does_not_change_can_recommend_or_create_places(world):
    map_id = world.map()
    world.ad(world.place("추천 불가 카페", can_recommend=False))
    world.ad(world.place("추천 가능 카페", can_recommend=True))
    before = world.db.execute(select(Place.id, Place.can_recommend).where(Place.name.like("추천%"))).all()

    list_ads(world, map_id)

    after = world.db.execute(select(Place.id, Place.can_recommend).where(Place.name.like("추천%"))).all()
    assert sorted(after) == sorted(before)

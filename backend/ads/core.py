"""
광고 선택 규칙(docs/ads.md 5절)의 순수 함수 — DB, 시계, 전역 랜덤을 보지 않는다. 지금 시각과 random.Random은 받아 쓴다.

선택 순서: running(기간과 active) → [places.api.get_ad_places가 open, 카테고리, 반경을 거른 결과] → choose(요청자의 최신 추천
결과 빼기, 균등 랜덤 최대 AD_SLOTS개) → on_map. 반응과 실격 조건은 입력에 없다 — 광고는 그 필터를 거치지 않는다(명세 2절 4번).
"""

import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ads.constants import AD_SLOTS, AD_STATS_TZ
from common import categories

# Asia/Seoul은 서머타임이 없어 +9 고정 오프셋과 같다. zoneinfo는 Windows에서 tzdata 패키지가 있어야 해서 쓰지 않는다
# (agent.core.KST와 같은 방식).
STATS_TZ = timezone(timedelta(hours=9), AD_STATS_TZ)
_NAME_MAX = 100      # api-spec AdPlace.name maxLength
_ADDRESS_MAX = 200   # api-spec AdPlace.address maxLength


@dataclass(frozen=True)
class ActiveAd:
    ad_id: str
    place_id: str
    starts_at: datetime
    ends_at: datetime
    active: bool


def running(ads: Sequence[ActiveAd], now: datetime) -> list[ActiveAd]:
    """active이고 starts_at <= now < ends_at인 광고."""
    return [a for a in ads if a.active and a.starts_at <= now < a.ends_at]


def request_categories(category: str | None) -> tuple[str, ...]:
    """요청 카테고리. 없으면 추천 대상 카테고리 전체."""
    return (category,) if category is not None else categories.recommendable()


def choose(
    ads: Sequence[ActiveAd], *, place_ids: Collection[str], excluded_place_ids: Collection[str], rng: random.Random,
    slots: int = AD_SLOTS,
) -> list[ActiveAd]:
    """place_ids(open, 카테고리, 반경을 통과한 장소)에 있고 excluded_place_ids(요청자의 최신 추천 결과)에 없는 광고 중
    균등 랜덤으로 최대 slots개. 후보가 slots개 이하면 전부다 — 반경 밖에서 채우지 않는다.
    입력 순서(DB 순서)에 결과가 흔들리지 않게 ad_id로 정렬한 뒤 뽑는다(같은 시드면 같은 결과)."""
    pool = sorted((a for a in ads if a.place_id in place_ids and a.place_id not in excluded_place_ids),
                  key=lambda a: a.ad_id)
    return rng.sample(pool, k=min(slots, len(pool)))


def on_map(place: Mapping[str, Any], *, db_place_ids: Collection[str], live_kakao_ids: Collection[str]) -> bool:
    """같은 place_id의 db 핀, 또는 같은 kakao_place_id의 실시간 핀(#382)이 이 지도에 있다."""
    if place["id"] in db_place_ids:
        return True
    kakao_id = place.get("kakao_place_id")
    return kakao_id is not None and kakao_id in live_kakao_ids


def stat_date(now: datetime) -> date:
    """집계 날짜 — AD_STATS_TZ 기준."""
    return now.astimezone(STATS_TZ).date()


def to_item(ad: ActiveAd, place: Mapping[str, Any], *, on_map: bool) -> dict:
    """api-spec Ad 모양. memo와 집계 값은 넣지 않는다. place_url은 places에 기록된 kakao_place_url뿐이다(#53)."""
    address = place.get("address")
    return {
        "ad_id": ad.ad_id,
        "place": {
            "place_id": place["id"],
            "name": place["name"][:_NAME_MAX],
            "category": place["category"],
            "address": address[:_ADDRESS_MAX] if address else None,
            "lat": place["lat"],
            "lng": place["lng"],
            "place_url": place.get("kakao_place_url"),
        },
        "on_map": on_map,
    }

"""
광고 조회와 클릭 기록(docs/ads.md 5절, 7절) — 명령형 셸. 규칙은 core.py에 있고 여기는 읽고 부르고 쓴다.

다른 모듈 데이터는 api.py로만 읽는다(#113): 장소는 places.api.get_ad_places, 요청자의 최신 추천 결과는
recommend.api.latest_run_place_ids, 이 지도의 핀은 pins.api 두 함수. 커밋하지 않는다 — 요청의 session_scope가 한 번 커밋한다.
그래서 노출 집계(served_count)는 조회와 같은 트랜잭션이다.
"""

import random
import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ads import core
from ads.constants import AD_RADIUS_M
from ads.models import Ad, AdDailyStat
from common.errors import AppError
from pins import api as pins_api
from places import api as places_api
from recommend import api as recommend_api


def list_ads(
    db: Session, *, map_id: str, user_id: str, category: str | None, center: tuple[float, float], now: datetime,
    rng: random.Random,
) -> list[dict]:
    """광고 칸 0~AD_SLOTS개(api-spec Ad 모양). 실린 광고마다 오늘(AD_STATS_TZ) served_count를 1 올린다."""
    ads = core.running(_load_active(db), now)
    if not ads:
        return []
    places = {
        p["id"]: p for p in places_api.get_ad_places(
            db, place_ids=[a.place_id for a in ads], center=center, radius_m=AD_RADIUS_M,
            categories=core.request_categories(category),
        )
    }
    if not places:
        return []
    excluded = recommend_api.latest_run_place_ids(db, map_id=map_id, requested_by=user_id, category=category)
    chosen = core.choose(ads, place_ids=places.keys(), excluded_place_ids=excluded, rng=rng)
    if not chosen:
        return []

    db_place_ids = pins_api.list_place_ids_on_map(db, map_id=map_id)
    live_kakao_ids = pins_api.list_live_kakao_ids_on_map(db, map_id=map_id)
    _increment(db, [a.ad_id for a in chosen], core.stat_date(now), "served_count")
    return [
        core.to_item(a, places[a.place_id], on_map=core.on_map(
            places[a.place_id], db_place_ids=db_place_ids, live_kakao_ids=live_kakao_ids))
        for a in chosen
    ]


def record_click(db: Session, *, ad_id: str, now: datetime) -> None:
    """click_count를 1 올린다. 광고 행이 없으면 NOT_FOUND. 기간이 끝났거나 inactive여도 행이 있으면 센다(명세 7.2)."""
    try:
        key = uuid.UUID(ad_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    if db.get(Ad, key) is None:
        raise AppError("NOT_FOUND")
    _increment(db, [str(key)], core.stat_date(now), "click_count")


def _load_active(db: Session) -> list[core.ActiveAd]:
    """active 광고 전부(부분 유니크라 장소당 하나). 기간은 core.running이 자른다."""
    rows = db.execute(
        select(Ad.id, Ad.place_id, Ad.starts_at, Ad.ends_at, Ad.active).where(Ad.active.is_(True))
    ).all()
    return [core.ActiveAd(str(r.id), r.place_id, r.starts_at, r.ends_at, r.active) for r in rows]


def _increment(db: Session, ad_ids: Sequence[str], stat_date: date, column: str) -> None:
    """(ad_id, stat_date) 행의 column을 1 올린다. 없으면 1로 만든다 — INSERT ... ON CONFLICT DO UPDATE 한 문장."""
    stmt = insert(AdDailyStat).values([{"ad_id": uuid.UUID(i), "stat_date": stat_date, column: 1} for i in ad_ids])
    stmt = stmt.on_conflict_do_update(
        index_elements=[AdDailyStat.ad_id, AdDailyStat.stat_date],
        set_={column: getattr(AdDailyStat, column) + 1},
    )
    db.execute(stmt)

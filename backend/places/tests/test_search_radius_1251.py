from types import SimpleNamespace
from math import degrees

import main  # noqa: F401
from sqlalchemy import text

from common.geo import EARTH_RADIUS_M
from places import api, ingest, repository, router
from places.schemas import PlaceSearchResult


def test_nearby_live_results_only_and_original_order(monkeypatch):
    monkeypatch.setattr(api, "check_search_rate", lambda _: None)
    monkeypatch.setattr(router, "_search_own", lambda *args: [])
    monkeypatch.setattr(router, "_fill_pinnable", lambda results, db: None)
    results = [
        PlaceSearchResult(place_id="near1", place_name="near1", lat=37.57, lng=126.98),
        PlaceSearchResult(place_id="far", place_name="far", lat=35.17, lng=129.07),
        PlaceSearchResult(place_id="near2", place_name="near2", lat=37.58, lng=126.98),
    ]
    monkeypatch.setattr(api, "search_by_name", lambda *args: results)
    found = router.search_places(q="가게", lat=37.5665, lng=126.978, limit=10,
                                 user=SimpleNamespace(user_id="u"), db=None)
    assert [result.place_id for result in found] == ["near1", "near2"]


def test_stages_keep_unbounded_search_without_coordinates():
    stages = api._search_stages(None)
    assert all(band == (None, None) for _, band, _ in stages)
    region, close = repository.REGION_RADIUS_M, repository.NEAR_RADIUS_M
    assert api._search_stages((37.5665, 126.978)) == [
        (api.TIER_NAME_PREFIX, (None, region), None),
        (api.TIER_NAME_PART, (None, close), None),
        (api.TIER_REST, (None, region), close),
    ]


def test_30km_boundary_in_own_db_and_kakao(db_session, monkeypatch):
    center = (37.5665, 126.978)
    radius = repository.REGION_RADIUS_M
    # PostGIS geography는 타원체 거리다. 기준에서 동쪽·서쪽으로 각각 0.1m 안팎을 만든다.
    def projected(distance, bearing):
        row = db_session.execute(text("""
            SELECT ST_Y(p::geometry), ST_X(p::geometry)
            FROM (SELECT ST_Project(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                                    :distance, radians(:bearing)) AS p) projected
        """), dict(lat=center[0], lng=center[1], distance=distance, bearing=bearing)).one()
        return row[0], row[1]

    inside = projected(radius - 0.1, 90)
    outside = projected(radius + 0.1, 270)
    repository.upsert_places(db_session, [
        ingest.PlaceRow("permit", "boundary-in", "경계검색 안", "음식점", None, None, *inside, "open"),
        ingest.PlaceRow("permit", "boundary-out", "경계검색 밖", "음식점", None, None, *outside, "open"),
    ])
    db_session.flush()
    assert [h.result.place_name for h in api.search_own_for_query("경계검색", center, 10, db=db_session)] == ["경계검색 안"]

    # 카카오는 구면 haversine 거리: 경도 고정 남북 방향에서 0.1m 안팎이다.
    live = [
        PlaceSearchResult(place_id="in", place_name="안", lat=center[0] + degrees((radius - 0.1) / EARTH_RADIUS_M), lng=center[1]),
        PlaceSearchResult(place_id="out", place_name="밖", lat=center[0] - degrees((radius + 0.1) / EARTH_RADIUS_M), lng=center[1]),
    ]
    monkeypatch.setattr(api, "check_search_rate", lambda _: None)
    monkeypatch.setattr(router, "_search_own", lambda *args: [])
    monkeypatch.setattr(router, "_fill_pinnable", lambda results, db: None)
    monkeypatch.setattr(api, "search_by_name", lambda *args: live)
    found = router.search_places(q="경계검색", lat=center[0], lng=center[1], limit=10,
                                 user=SimpleNamespace(user_id="u"), db=db_session)
    assert [r.place_id for r in found] == ["in"]

from types import SimpleNamespace

import main  # noqa: F401
from places import api, router
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
    assert all(band[1] == api.repository.REGION_RADIUS_M or band[1] == api.repository.NEAR_RADIUS_M
               for _, band, _ in api._search_stages((37.5665, 126.978)))

"""#244 — 입력 길이 제한(api-spec.yaml maxLength 100)."""

import pytest
from pydantic import ValidationError

from maps.schemas import MapCreateRequest, MapRegion, MapUpdateRequest


def test_title_and_region_label_accept_100_and_reject_101():
    region = {"label": "가" * 100, "lat": 37.5, "lng": 127.0}
    MapCreateRequest(title="가" * 100, start_date="2026-11-01", end_date="2026-11-02", region=region)
    with pytest.raises(ValidationError):
        MapCreateRequest(title="가" * 101, start_date="2026-11-01", end_date="2026-11-02")
    with pytest.raises(ValidationError):
        MapRegion(label="가" * 101, lat=37.5, lng=127.0)


# --- 요청 제약이 스펙과 같다(#733) ---

@pytest.mark.parametrize("lat, lng", [(-90, -180), (90, 180), (0, 0)])
def test_region_accepts_the_spec_bounds(lat, lng):
    assert MapRegion(label="가", lat=lat, lng=lng).lat == lat


@pytest.mark.parametrize("lat, lng", [(90.01, 0), (-90.01, 0), (0, 180.01), (0, -180.01)])
def test_region_rejects_coordinates_outside_the_spec_bounds(lat, lng):
    with pytest.raises(ValidationError):
        MapRegion(label="가", lat=lat, lng=lng)


def test_update_request_rejects_an_empty_title():
    with pytest.raises(ValidationError):
        MapUpdateRequest(title="")
    assert MapUpdateRequest(title="가").title == "가"

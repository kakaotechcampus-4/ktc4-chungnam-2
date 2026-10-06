"""#244 — 입력 길이 제한(api-spec.yaml maxLength 100)."""

import pytest
from pydantic import ValidationError

from maps.schemas import MapCreateRequest, MapRegion


def test_title_and_region_label_accept_100_and_reject_101():
    region = {"label": "가" * 100, "lat": 37.5, "lng": 127.0}
    MapCreateRequest(title="가" * 100, start_date="2026-11-01", end_date="2026-11-02", region=region)
    with pytest.raises(ValidationError):
        MapCreateRequest(title="가" * 101, start_date="2026-11-01", end_date="2026-11-02")
    with pytest.raises(ValidationError):
        MapRegion(label="가" * 101, lat=37.5, lng=127.0)

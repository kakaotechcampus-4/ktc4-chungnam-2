"""#733 — 핀 요청 모델이 스펙 제약을 그대로 가진다(DB 없이 모델만 본다)."""

import pytest
from pydantic import ValidationError

from pins.schemas import BulkPinRequest, PinCreateSearch

SEARCH = {"category": "음식점", "place_id": "kakao:1", "place_name": "성수 칼국수", "lat": 37.5, "lng": 127.0}


def test_link_url_over_2000_chars_is_rejected_by_the_model():
    with pytest.raises(ValidationError):
        PinCreateSearch(**SEARCH, link_url="x" * 2001)


def test_bulk_keeps_items_raw_so_one_bad_item_does_not_fail_the_request():
    req = BulkPinRequest(pins=[{"garbage": 1}, SEARCH])
    assert all(type(item) is dict for item in req.pins)


@pytest.mark.parametrize("pins", [[], [SEARCH] * 31])
def test_bulk_size_limits_stay(pins):
    with pytest.raises(ValidationError):
        BulkPinRequest(pins=pins)

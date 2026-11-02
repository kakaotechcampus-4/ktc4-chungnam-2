"""#1047·#1048 — LinkParseResult에 번호·주소 후보 칸이 생겨도 기존 응답은 그대로다(모델만 본다)."""

import pytest
from pydantic import ValidationError

from places.schemas import LinkParseResult, PlaceSearchResult


def _place(i: int) -> PlaceSearchResult:
    return PlaceSearchResult(place_id=f"own:{i}", place_name="가게", lat=37.5, lng=127.0, category="음식점", pinnable=True)


def test_new_fields_default_to_nothing_and_are_left_out_of_the_response():
    result = LinkParseResult(provider="kakao", matches=[], needs_search_query=True)
    assert "address_candidates" not in result.model_dump(exclude_none=True)
    assert result.external_id is None and result.address_candidates is None and result.matched_by is None


def test_old_shaped_payload_still_parses_and_new_values_are_accepted():
    old = {"provider": "google", "matches": [], "needs_search_query": False, "matched_by": "hint"}
    assert LinkParseResult(**old).matched_by == "hint"
    new = LinkParseResult(provider="naver", external_id="naver:1412566798", matched_by="external_id",
                          matches=[_place(1)], needs_search_query=False, address_candidates=[_place(2)])
    assert new.external_id == "naver:1412566798" and new.matched_by == "external_id"


def test_limits_follow_the_spec():
    with pytest.raises(ValidationError):
        LinkParseResult(provider="naver", external_id="x" * 101, matches=[], needs_search_query=True)
    with pytest.raises(ValidationError):
        LinkParseResult(provider="kakao", matches=[], needs_search_query=True, address_candidates=[_place(i) for i in range(4)])

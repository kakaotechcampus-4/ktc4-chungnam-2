"""
PlaceGateway 포트의 dev/real 공통 계약. common.contracts.assert_signature_matches로 Protocol과
구현의 메서드 이름·인자·반환 타입이 같은지 본다(mentor-review-plan.md §10).
"""

import pytest

from common.contracts import assert_signature_matches
from pins.deps import RequestEchoPlaceGateway
from pins.ports import PlaceGateway


def test_dev_place_gateway_matches_protocol():
    assert_signature_matches(PlaceGateway, RequestEchoPlaceGateway)


@pytest.mark.skip(reason="places(#34) 실구현이 아직 없다 — 도착하면 이 테스트를 채운다")
def test_real_place_gateway_matches_protocol():
    pass

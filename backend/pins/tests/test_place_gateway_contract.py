"""
PlaceGateway 포트의 dev/real 공통 계약. common.contracts.assert_signature_matches로 Protocol과
구현의 메서드 이름·인자·반환 타입이 같은지 본다(mentor-review-plan.md §10).
"""

from common.contracts import assert_signature_matches
from pins.deps import RealPlaceGateway, RequestEchoPlaceGateway
from pins.ports import PlaceGateway


def test_dev_place_gateway_matches_protocol():
    assert_signature_matches(PlaceGateway, RequestEchoPlaceGateway)


def test_real_place_gateway_matches_protocol():
    assert_signature_matches(PlaceGateway, RealPlaceGateway)

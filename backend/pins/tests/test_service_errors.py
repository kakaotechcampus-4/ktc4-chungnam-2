"""
service.create_pin의 IntegrityError 분기 — uq_pins_map_place 위반이 아닌 무결성 오류를
409 PIN_DUPLICATE로 둔갑시키지 않는지 확인한다(docs/code-quality.md "실패를 감추는 코드").
실제 DB 없이 Session을 가짜로 대체해 이 분기만 좁혀서 검증한다.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from pins import service
from pins.ports import ResolvedPlace
from pins.schemas import PinCreateRequest


class _FakeOrig(Exception):
    def __init__(self, pgcode: str, message: str):
        self.pgcode = pgcode
        super().__init__(message)


def test_non_duplicate_integrity_error_is_not_disguised_as_409():
    db = MagicMock()
    db.execute.return_value.first.return_value = None  # 사전조회: 중복 아님

    not_null_violation = _FakeOrig("23502", "null value in column violates not-null constraint")
    db.flush.side_effect = IntegrityError("INSERT ...", {}, not_null_violation)

    places = MagicMock()
    places.resolve.return_value = ResolvedPlace(place_id="p1", lat=35.1, lng=129.0)
    membership = MagicMock()
    membership.is_member.return_value = True
    publisher = MagicMock()

    req = PinCreateRequest(category="음식점", source="coordinate", lat=35.1, lng=129.0)

    with pytest.raises(IntegrityError):
        service.create_pin(db, "map_1", "user_1", req, places, membership, publisher)

    # 발행되지 않아야 한다 — 실패한 생성이 이벤트로 새면 안 된다.
    publisher.publish.assert_not_called()


def test_unique_violation_on_map_place_constraint_becomes_409():
    db = MagicMock()
    db.execute.return_value.first.return_value = None  # 사전조회 시점엔 아직 안 보임(레이스)

    unique_violation = _FakeOrig(
        "23505",
        'duplicate key value violates unique constraint "uq_pins_map_place"',
    )
    db.flush.side_effect = IntegrityError("INSERT ...", {}, unique_violation)

    places = MagicMock()
    places.resolve.return_value = ResolvedPlace(place_id="p1", lat=35.1, lng=129.0)
    membership = MagicMock()
    membership.is_member.return_value = True
    publisher = MagicMock()

    req = PinCreateRequest(category="음식점", source="coordinate", lat=35.1, lng=129.0)

    from pins.errors import PinError

    with pytest.raises(PinError) as exc_info:
        service.create_pin(db, "map_1", "user_1", req, places, membership, publisher)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "PIN_DUPLICATE"
    publisher.publish.assert_not_called()

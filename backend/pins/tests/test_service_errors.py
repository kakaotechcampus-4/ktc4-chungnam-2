"""
service.create_pin의 IntegrityError 분기 — uq_pins_map_place 위반이 아닌 무결성 오류를
409 PIN_DUPLICATE로 둔갑시키지 않는지 확인한다(docs/code-quality.md "실패를 감추는 코드").
실제 DB 없이 Session을 가짜로 대체해 이 분기만 좁혀서 검증한다.

이 테스트가 정확히 증명하는 것: create_pin이 예외를 분류하는 로직 자체가 맞는지(그리고 그
경로에서 이벤트가 기록되지 않는지)다. 세션이 진짜로 커밋/롤백되는지는 이 단위 테스트의 관심사가
아니다 — 그건 test_pins_api.py의 통합 테스트가 실제 트랜잭션으로 증명한다.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from authz.core import Principal
from common.errors import AppError
from pins import service
from pins.ports import ResolvedPlace
from pins.schemas import PinCreateRequest


class _FakeOrig(Exception):
    def __init__(self, pgcode: str, message: str):
        self.pgcode = pgcode
        super().__init__(message)


def _make_db_with_integrity_error(orig: Exception) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.first.return_value = None  # 사전조회: 중복 아님
    # MagicMock의 __exit__ 기본 반환값은 truthy라, 그냥 두면 with db.begin_nested(): 블록이
    # IntegrityError를 조용히 삼켜버려 아래 except가 아예 실행되지 않는다 — 명시적으로 False를
    # 줘서 예외가 실제로 빠져나가게 한다.
    db.begin_nested.return_value.__exit__.return_value = False
    db.flush.side_effect = IntegrityError("INSERT ...", {}, orig)
    return db


def _principal() -> Principal:
    return Principal(user_id="user_1", map_id="map_1", role="member")


def _req() -> PinCreateRequest:
    return PinCreateRequest(category="음식점", source="coordinate", lat=35.1, lng=129.0)


def test_non_duplicate_integrity_error_is_not_disguised_as_409():
    not_null_violation = _FakeOrig("23502", "null value in column violates not-null constraint")
    db = _make_db_with_integrity_error(not_null_violation)

    places = MagicMock()
    places.resolve.return_value = ResolvedPlace(place_id="p1", lat=35.1, lng=129.0)

    with patch("pins.service.record_event") as record_event_mock:
        with pytest.raises(IntegrityError):
            service.create_pin(db, "map_1", _principal(), _req(), places)
        # 발행되지 않아야 한다 — 실패한 생성이 이벤트로 새면 안 된다.
        record_event_mock.assert_not_called()


def test_unique_violation_on_map_place_constraint_becomes_409():
    unique_violation = _FakeOrig(
        "23505",
        'duplicate key value violates unique constraint "uq_pins_map_place"',
    )
    db = _make_db_with_integrity_error(unique_violation)

    places = MagicMock()
    places.resolve.return_value = ResolvedPlace(place_id="p1", lat=35.1, lng=129.0)

    with patch("pins.service.record_event") as record_event_mock:
        with pytest.raises(AppError) as exc_info:
            service.create_pin(db, "map_1", _principal(), _req(), places)
        record_event_mock.assert_not_called()

    assert exc_info.value.status == 409
    assert exc_info.value.code == "PIN_DUPLICATE"

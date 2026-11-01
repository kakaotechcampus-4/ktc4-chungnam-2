"""common/cursor.py — 목록 커서 왕복과 잘못된 값(#973). notifications·reviews의 커서 테스트를 여기로 모았다."""

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from common.cursor import decode_cursor, encode_cursor

KST_NOON = datetime(2026, 10, 15, 12, 30, 1, 123456, tzinfo=timezone(timedelta(hours=9)))
UTC_T0 = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("at", [KST_NOON, UTC_T0])
def test_round_trip_is_url_safe(at):
    row_id = uuid.uuid4()
    cursor = encode_cursor(at, row_id)
    assert all(c.isalnum() or c in "-_" for c in cursor)    # '+'·'='가 없어 쿼리 문자열에 그대로 실을 수 있다
    assert decode_cursor(cursor) == (at, row_id)


def test_format_is_base64url_of_created_at_and_id():
    """이미 발급된 커서가 계속 읽혀야 한다 — 형식(`isoformat|uuid`, 패딩 없는 base64url)을 고정한다."""
    row_id = uuid.UUID(int=7)
    raw = f"{UTC_T0.isoformat()}|{row_id}".encode()
    issued = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert encode_cursor(UTC_T0, row_id) == issued
    assert decode_cursor(issued) == (UTC_T0, row_id)


@pytest.mark.parametrize("bad", [
    "", "!!!", "nope", "%%%", "aGVsbG8",
    "MjAyNi0xMC0xNXxub3QtYS11dWlk",                   # "2026-10-15|not-a-uuid"
    "MjAyNi0xMS0wMVQwMzowMDowMHxub3QtYS11dWlk",       # "2026-11-01T03:00:00|not-a-uuid"
    encode_cursor(UTC_T0, uuid.uuid4())[:-3] + "!!!",
])
def test_bad_cursor_raises_value_error(bad):
    with pytest.raises(ValueError):
        decode_cursor(bad)


def test_cursor_without_timezone_is_rejected():
    raw = base64.urlsafe_b64encode(f"2026-10-15T12:00:00|{uuid.uuid4()}".encode()).decode()
    with pytest.raises(ValueError):
        decode_cursor(raw)


def test_error_message_does_not_echo_the_input():
    """받은 커서는 사용자 입력이다 — 예외 메시지에 싣지 않는다(backend/CLAUDE.md 실패 로그)."""
    secret = "my-search-words-1234"
    with pytest.raises(ValueError) as exc:
        decode_cursor(secret)
    assert secret not in str(exc.value)

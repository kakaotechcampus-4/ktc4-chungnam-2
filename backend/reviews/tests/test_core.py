"""후기 순수 규칙 — 장소 찾기, 평균 반올림, 쪽 나누기, 응답 조립. DB 없이 직접 부른다. 커서 자체는 common/tests/test_cursor.py(#973)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from common.cursor import decode_cursor
from common.errors import AppError
from reviews import core

T0 = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)


def _row(i: int, user_id: str = "someone") -> core.ReviewRow:
    return core.ReviewRow(id=uuid.UUID(int=i), user_id=user_id, rating=4, body=f"후기 {i}",
                          created_at=T0 - timedelta(minutes=i), updated_at=T0)


def test_place_of_db_pin_is_its_place():
    assert core.place_of("db", "p1") == "p1"


@pytest.mark.parametrize("source, place_id", [("live", None), ("live", "p1"), ("db", None), ("db", "")])
def test_place_of_live_or_missing_place_is_place_not_supported(source, place_id):
    with pytest.raises(AppError) as exc:
        core.place_of(source, place_id)
    assert (exc.value.code, exc.value.status) == ("PLACE_NOT_SUPPORTED", 422)


@pytest.mark.parametrize("total, count, expected", [
    (0, 0, None), (5, 1, 5.0), (13, 3, 4.3), (17, 4, 4.3), (9, 2, 4.5), (29, 20, 1.5), (43, 10, 4.3),
])
def test_average_is_one_decimal_rounding_half_up(total, count, expected):
    assert core.average(total, count) == expected


def test_page_marks_mine_and_cursor_points_at_last_shown():
    rows = [_row(i, "me" if i == 1 else "other") for i in range(4)]

    items, cursor = core.page(rows, viewer_id="me", page_size=3)

    assert [i["is_mine"] for i in items] == [False, True, False]
    assert "user_id" not in items[0]
    assert decode_cursor(cursor) == (rows[2].created_at, rows[2].id)


def test_page_without_more_rows_has_no_cursor():
    items, cursor = core.page([_row(0)], viewer_id="me", page_size=3)
    assert len(items) == 1 and cursor is None

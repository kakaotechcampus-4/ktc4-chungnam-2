from datetime import datetime, timedelta, timezone

import pytest

from common.kst import KST, kst_date, kst_day_start

UTC = timezone.utc


def test_kst_is_a_fixed_plus_nine_offset():
    assert KST.utcoffset(None) == timedelta(hours=9)


def test_utc_afternoon_is_already_the_next_kst_day():
    now = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)   # KST 10-30 00:00

    assert kst_date(now).isoformat() == "2026-10-30"
    assert kst_day_start(now) == datetime(2026, 10, 30, tzinfo=KST)


def test_one_minute_before_kst_midnight_is_the_same_day():
    now = datetime(2026, 10, 29, 14, 59, tzinfo=UTC)   # KST 10-29 23:59

    assert kst_date(now).isoformat() == "2026-10-29"
    assert kst_day_start(now) == datetime(2026, 10, 29, tzinfo=KST)


def test_day_start_is_the_same_instant_in_utc():
    now = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)

    assert kst_day_start(now).astimezone(UTC) == datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


def test_naive_datetime_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        kst_date(datetime(2026, 10, 30, 12, 0))

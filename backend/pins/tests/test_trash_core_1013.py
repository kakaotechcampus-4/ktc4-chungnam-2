"""#1013 — 휴지통 날짜 계산(DB 없음). 목록과 복구가 같은 경계를 쓴다."""

from datetime import datetime, timedelta, timezone

import pytest

from pins import core

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("ago_days, left, restorable", [
    (0, 30, True),
    (0.5, 30, True),
    (1, 29, True),
    (29, 1, True),
    (29.5, 1, True),
    (29.99, 1, True),     # 올림 — 지금 복구할 수 있으면 1 이상
    (30, 0, False),       # 정확히 30일이면 정리 대상이다(purge는 deleted_at <= now-30일)
    (31, 0, False),
])
def test_days_left_rounds_up_and_matches_restorable(ago_days, left, restorable):
    deleted_at = NOW - timedelta(days=ago_days)
    assert core.trash_days_left(deleted_at, NOW) == left
    assert core.is_restorable(deleted_at, NOW) is restorable
    assert core.trash_purge_at(deleted_at) == deleted_at + timedelta(days=30)

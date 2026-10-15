"""기준 시간(명세 6.1, 17절 5번) — 이벤트 6개 미만, clamp 1시간과 12시간, D-day 경계 15, 14, 4, 3, 여행 중."""

from datetime import timedelta

import pytest

from agent import core
from agent.tests.snaps import NOW, TODAY, hours


def _times(gaps_hours: list[float]):
    """마지막이 NOW인 시각 목록. gaps는 앞에서부터의 간격."""
    times = [NOW]
    for gap in reversed(gaps_hours):
        times.insert(0, times[0] - hours(gap))
    return times


@pytest.mark.parametrize("n_events", [0, 1, 5])
def test_fewer_than_six_events_use_default_base_without_multiplier(n_events):
    times = _times([0.1] * (n_events - 1)) if n_events else []

    assert core.rhythm_base(times) == hours(3)
    assert core.time_threshold(times, TODAY + timedelta(days=30), TODAY) == hours(3)   # 3시간 × 1.0


def test_six_events_use_median_gap_times_multiplier():
    times = _times([2, 2, 2, 2, 2])   # 6개, 간격 2시간

    assert core.rhythm_base(times) == hours(6)


def test_median_of_even_gap_count():
    times = _times([1, 1, 3, 3, 3, 1])   # 간격 6개 → 중앙값 (1+3)/2 = 2시간

    assert core.rhythm_base(times) == hours(6)


def test_only_last_twenty_events_count():
    old = _times([50] * 10)                       # 오래된 큰 간격
    recent = [old[-1] + hours(1) * i for i in range(1, 21)]   # 최근 20개, 간격 1시간

    assert core.rhythm_base(old + recent) == hours(3)


def test_default_base_with_dday_factor():
    """이벤트가 적으면 3시간에 D-day 계수만 곱한다."""
    assert core.time_threshold([], TODAY + timedelta(days=10), TODAY) == hours(1.5)   # × 0.5


def test_clamped_to_one_hour_minimum():
    times = _times([1 / 60] * 6)   # 간격 1분 → 3분

    assert core.time_threshold(times, TODAY + timedelta(days=30), TODAY) == hours(1)
    assert core.time_threshold([], TODAY, TODAY) == hours(1)   # 3시간 × 0.25 = 45분 → 1시간


def test_clamped_to_twelve_hours_maximum():
    times = _times([10] * 6)   # 간격 10시간 → 30시간

    assert core.time_threshold(times, TODAY + timedelta(days=30), TODAY) == hours(12)


@pytest.mark.parametrize(
    ("days_left", "factor"),
    [(30, 1.0), (15, 1.0), (14, 0.5), (4, 0.5), (3, 0.25), (0, 0.25), (-1, 0.25)],
    ids=["D-30", "D-15", "D-14", "D-4", "D-3", "D-day", "traveling"],
)
def test_dday_factor_boundaries(days_left, factor):
    assert core.dday_factor(TODAY + timedelta(days=days_left), TODAY) == factor


def test_threshold_scales_with_dday():
    times = _times([2] * 6)   # 리듬 6시간

    assert core.time_threshold(times, TODAY + timedelta(days=15), TODAY) == hours(6)
    assert core.time_threshold(times, TODAY + timedelta(days=14), TODAY) == hours(3)
    assert core.time_threshold(times, TODAY + timedelta(days=3), TODAY) == hours(1.5)
    assert core.time_threshold(times, TODAY - timedelta(days=1), TODAY) == hours(1.5)   # 여행 중

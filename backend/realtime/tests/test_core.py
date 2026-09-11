"""core.py::advance 유닛 테스트 — DB 불필요(mentor-review-plan.md §검증)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from realtime.core import GRACE, advance

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Row:
    seq: int


def test_emits_contiguous_prefix():
    emit, last, gaps = advance(8, [Row(9), Row(10), Row(12)], NOW, {})
    assert [r.seq for r in emit] == [9, 10]
    assert last == 10
    assert 11 in gaps


def test_fills_gap_when_late_row_arrives():
    _, last, gaps = advance(10, [], NOW, {11: NOW})
    emit, last, gaps = advance(last, [Row(11), Row(12)], NOW, gaps)
    assert [r.seq for r in emit] == [11, 12]


def test_skips_gap_after_grace_period():
    """구멍을 낸 row(12) 자체가 emit에 포함돼야 한다."""
    gaps = {11: NOW - GRACE - timedelta(seconds=1)}
    emit, last, gaps = advance(10, [Row(12)], NOW, gaps)
    assert [r.seq for r in emit] == [12]
    assert last == 12


def test_no_rows_leaves_state_unchanged():
    emit, last, gaps = advance(5, [], NOW, {})
    assert emit == [] and last == 5 and gaps == {}


def test_fresh_gap_waits_without_emitting():
    """구멍이 막 생겼을 때(아직 GRACE 안 지남)는 아무 것도 안 내보내고 기다린다."""
    emit, last, gaps = advance(0, [Row(5)], NOW, {})
    assert emit == [] and last == 0 and 1 in gaps

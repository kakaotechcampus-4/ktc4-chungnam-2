"""core.py::advance 유닛 테스트 — DB 불필요(mentor-review-plan.md §검증)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from realtime.core import GRACE, CloseScope, advance, close_after

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


# ── close_after: 어떤 행 다음에 어떤 구독을 닫는가 (#369) ──

@dataclass(frozen=True)
class EventRow:
    map_id: str
    type: str
    payload: dict


def test_map_deleted_closes_every_subscription_on_the_map():
    scope = close_after(EventRow("m1", "map.deleted", {"map_id": "m1"}))
    assert scope == CloseScope("m1")
    assert scope.covers("anyone")


def test_member_left_closes_only_that_users_subscriptions():
    scope = close_after(EventRow("m1", "member.left", {"map_id": "m1", "user_id": "u1", "new_owner_user_id": "u2"}))
    assert scope == CloseScope("m1", "u1")
    assert scope.covers("u1")
    assert not scope.covers("u2")


def test_member_left_without_user_id_closes_nothing():
    assert close_after(EventRow("m1", "member.left", {"map_id": "m1"})) is None


def test_other_events_close_nothing():
    assert close_after(EventRow("m1", "pin.created", {})) is None
    assert close_after(EventRow("m1", "member.joined", {"user_id": "u1"})) is None

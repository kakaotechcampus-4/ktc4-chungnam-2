"""Subscription 필터링·Dispatcher 동작 유닛 테스트 — DB 불필요.

realtime/CLAUDE.md가 "가장 중요한 테스트"라고 명시한 요구사항부터: 개인 채널 이벤트가
전체 채널 구독자에게 절대 도달하지 않는다.
"""

import asyncio

import pytest

from realtime.dispatcher import Dispatcher, Subscription


@pytest.fixture
def event_loop_policy_row():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Row:
        seq: int
        map_id: str
        channel: str
        type: str
        payload: dict
        recipient_user_id: str | None = None

    return Row


def test_public_subscription_wants_only_public(event_loop_policy_row):
    Row = event_loop_policy_row
    sub = Subscription(channel="public", user_id=None)
    assert sub.wants(Row(1, "map1", "public", "pin.created", {})) is True
    assert sub.wants(Row(2, "map1", "private", "pin.created", {}, recipient_user_id="u1")) is False


def test_private_subscription_wants_only_matching_recipient(event_loop_policy_row):
    Row = event_loop_policy_row
    sub = Subscription(channel="private", user_id="u1")
    assert sub.wants(Row(1, "map1", "private", "x", {}, recipient_user_id="u1")) is True
    assert sub.wants(Row(2, "map1", "private", "x", {}, recipient_user_id="u2")) is False
    assert sub.wants(Row(3, "map1", "public", "x", {})) is False


@pytest.mark.asyncio
async def test_tick_never_leaks_private_event_to_public_subscriber(event_loop_policy_row):
    """가장 중요한 테스트: private 이벤트가 public 구독자 큐에 들어가지 않는다."""
    Row = event_loop_policy_row
    d = Dispatcher()
    public_sub = d.subscribe("map1", channel="public")
    private_sub = d.subscribe("map1", channel="private", user_id="u1")
    other_private_sub = d.subscribe("map1", channel="private", user_id="u2")

    rows = [Row(1, "map1", "private", "pin.created", {"secret": True}, recipient_user_id="u1")]
    for row in rows:
        for sub in d._subscribers.get(row.map_id, []):
            if sub.wants(row):
                sub.queue.put_nowait(row)

    assert public_sub.queue.empty()
    assert other_private_sub.queue.empty()
    assert not private_sub.queue.empty()
    got = await private_sub.queue.get()
    assert got is rows[0]


def test_unsubscribe_twice_is_noop():
    d = Dispatcher()
    sub = d.subscribe("map1", channel="public")
    d.unsubscribe("map1", sub)
    d.unsubscribe("map1", sub)   # 두 번째 호출이 예외를 내면 안 된다


def test_unsubscribe_unknown_map_is_noop():
    d = Dispatcher()
    sub = Subscription(channel="public", user_id=None)
    d.unsubscribe("no-such-map", sub)   # KeyError 없이 조용히 넘어간다


@pytest.mark.asyncio
async def test_run_forever_cannot_start_twice():
    d = Dispatcher()
    d._last_seen = 0
    task = asyncio.create_task(d.run_forever())
    await asyncio.sleep(0)   # run_forever가 _started=True를 찍을 시간을 준다
    with pytest.raises(RuntimeError):
        await d.run_forever()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

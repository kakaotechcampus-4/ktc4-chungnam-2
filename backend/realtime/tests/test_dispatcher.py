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
    sub = Subscription(channel="public", user_id="u1")
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
    public_sub = d.subscribe("map1", channel="public", user_id="u1")
    private_sub = d.subscribe("map1", channel="private", user_id="u1")
    other_private_sub = d.subscribe("map1", channel="private", user_id="u2")

    rows = [Row(1, "map1", "private", "pin.created", {"secret": True}, recipient_user_id="u1")]
    d._deliver(rows)

    assert public_sub.queue.empty()
    assert other_private_sub.queue.empty()
    assert not private_sub.queue.empty()
    got = await private_sub.queue.get()
    assert got is rows[0]


def test_unsubscribe_twice_is_noop():
    d = Dispatcher()
    sub = d.subscribe("map1", channel="public", user_id="u1")
    d.unsubscribe("map1", sub)
    d.unsubscribe("map1", sub)   # 두 번째 호출이 예외를 내면 안 된다


def test_unsubscribe_unknown_map_is_noop():
    d = Dispatcher()
    sub = Subscription(channel="public", user_id="u1")
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

@pytest.mark.asyncio
async def test_tick_failure_recovers_and_logs_only_type(monkeypatch, caplog):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    d = Dispatcher()
    calls = 0

    def tick():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("sensitive database detail")
        d.request_stop()

    monkeypatch.setattr(d, "_tick", tick)
    await asyncio.wait_for(d.run_forever(), 1)
    assert calls == 2
    assert d.error_count == 1
    assert d.last_success_at is not None
    assert "RuntimeError" in caplog.text
    assert "sensitive database detail" not in caplog.text


@pytest.mark.asyncio
async def test_continuous_failure_makes_health_unhealthy(monkeypatch):
    import realtime.dispatcher as module
    from fastapi import Response
    from main import app, dispatcher, health

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    monkeypatch.setattr(module, "MAX_RETRY_INTERVAL", 0.002)
    monkeypatch.setattr(module, "POLL_STALE_SECONDS", 0.01)

    def fail():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(dispatcher, "_tick", fail)
    task = asyncio.create_task(dispatcher.run_forever())
    monkeypatch.setattr(app.state, "dispatcher_task", task, raising=False)
    try:
        await asyncio.sleep(0.05)
        response = Response()
        assert health(response) == {"status": "error"}
        assert response.status_code == 503
        assert dispatcher.error_count > 0
    finally:
        dispatcher.request_stop()
        await task
    response = Response()
    assert health(response) == {"status": "error"}
    assert response.status_code == 503

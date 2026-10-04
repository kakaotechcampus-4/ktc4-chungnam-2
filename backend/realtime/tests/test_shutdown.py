"""서버 종료 처리(#130) — dispatcher 정지 → SSE 정리 → 연결 풀 닫기 순서와 "빠르게 끝남" 검증.
DB 불필요: 기동 시 조회와 _tick, engine.dispose를 대체한다.
"""

import asyncio
import time

import pytest

import main
from realtime.dispatcher import Dispatcher
from realtime.router import public_events


class _AliveRequest:
    async def is_disconnected(self) -> bool:
        return False   # 클라이언트는 계속 붙어 있다 — 종료 신호만이 연결을 끊을 수 있다


@pytest.mark.asyncio
async def test_lifespan_exit_is_fast_and_ordered_with_open_sse(monkeypatch):
    events: list[str] = []
    d = main.dispatcher

    def slow_tick():
        time.sleep(0.3)   # 진행 중인 DB 조회 흉내
        events.append("tick_done")

    monkeypatch.setattr(d, "initialize_last_seen", lambda: None)
    monkeypatch.setattr(d, "_tick", slow_tick)
    monkeypatch.setattr(main.engine, "dispose", lambda *a, **k: events.append("dispose"))
    monkeypatch.setattr("realtime.dispatcher.POLL_INTERVAL", 0.05)

    sse_done = asyncio.Event()

    async def consume():
        response = await public_events(request=_AliveRequest(), mapId="m1", last_event_id=None)
        async for _ in response.body_iterator:
            pass
        events.append("sse_closed")
        sse_done.set()

    consumer = None
    async with main.lifespan(main.app):
        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.1)   # SSE 구독 완료 + _tick이 돌기 시작할 시간
        assert not consumer.done()
        started = time.monotonic()

    elapsed = time.monotonic() - started
    await asyncio.wait_for(sse_done.wait(), timeout=1)
    await consumer

    assert elapsed < 1.0   # 강제 종료 대기(제한 시간) 없이 끝난다
    assert events.index("tick_done") < events.index("dispose")   # 진행 중 조회가 끝난 뒤에 풀을 닫는다
    assert "sse_closed" in events
    assert d._subscribers == {}


@pytest.mark.asyncio
async def test_run_forever_stops_by_signal_and_can_restart(monkeypatch):
    monkeypatch.setattr("realtime.dispatcher.POLL_INTERVAL", 0.01)
    d = Dispatcher()
    ticks = []
    monkeypatch.setattr(d, "_tick", lambda: ticks.append(1))
    for _ in range(2):   # 정지 후 다시 시작해도 "두 번 시작" 에러가 나지 않는다
        task = asyncio.create_task(d.run_forever())
        await asyncio.sleep(0.05)
        d.request_stop()
        await asyncio.wait_for(task, timeout=1)   # CancelledError 없이 정상 반환
    assert ticks


@pytest.mark.asyncio
async def test_subscribe_after_close_is_already_closed():
    d = Dispatcher()
    d.close_subscriptions()
    sub = d.subscribe("m1", channel="public")
    from realtime.dispatcher import CLOSED

    assert sub.queue.get_nowait() is CLOSED


@pytest.mark.asyncio
async def test_lifespan_leaves_no_closed_state_behind(monkeypatch):
    """종료가 끝난 뒤 싱글턴에 닫힘 상태가 남으면 다음 lifespan/테스트의 구독이 이미 닫힌 채로 나온다."""
    d = main.dispatcher
    monkeypatch.setattr(d, "initialize_last_seen", lambda: None)
    monkeypatch.setattr(d, "_tick", lambda: None)
    monkeypatch.setattr(main.engine, "dispose", lambda *a, **k: None)
    async with main.lifespan(main.app):
        pass
    sub = d.subscribe("m-after", channel="public")
    try:
        assert sub.queue.empty()
    finally:
        d.unsubscribe("m-after", sub)


@pytest.mark.asyncio
async def test_lifespan_exit_does_not_hang_when_tick_blocks(monkeypatch):
    d = main.dispatcher
    monkeypatch.setattr(d, "initialize_last_seen", lambda: None)
    monkeypatch.setattr(d, "_tick", lambda: time.sleep(0.5))   # 종료 상한보다 오래 막힌 조회
    monkeypatch.setattr(main.engine, "dispose", lambda *a, **k: None)
    monkeypatch.setattr(main, "SHUTDOWN_TIMEOUT", 0.05)
    monkeypatch.setattr("realtime.dispatcher.POLL_INTERVAL", 0.01)
    async with main.lifespan(main.app):
        await asyncio.sleep(0.1)   # _tick이 돌고 있는 중
        started = time.monotonic()
    assert time.monotonic() - started < 0.4   # 상한 초과 시 취소하고 계속 진행

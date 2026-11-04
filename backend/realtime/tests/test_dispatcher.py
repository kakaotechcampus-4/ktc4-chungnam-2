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
    assert d.error_count == 1   # 정지 뒤에도 오류 횟수는 남는다(last_success_at은 정지 때 지운다)
    assert "RuntimeError" in caplog.text
    assert "sensitive database detail" not in caplog.text


@pytest.fixture
def global_dispatcher(monkeypatch):
    """전역 main.dispatcher / app.state.dispatcher_task를 쓰는 시험이 상태를 남기지 않게 한다.
    monkeypatch가 속성을 되돌리고, 남은 가변 상태는 시험 뒤 초기값으로 복원한다."""
    import realtime.dispatcher as module
    from main import app, dispatcher

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    monkeypatch.setattr(module, "MAX_RETRY_INTERVAL", 0.002)
    had_task = hasattr(app.state, "dispatcher_task")
    old_task = getattr(app.state, "dispatcher_task", None)
    yield app, dispatcher
    dispatcher.request_stop()
    dispatcher._stop_requested = False
    dispatcher._started = False
    dispatcher.error_count = 0
    dispatcher.last_success_at = None
    dispatcher._health_since = None
    if had_task:
        app.state.dispatcher_task = old_task
    elif hasattr(app.state, "dispatcher_task"):
        del app.state.dispatcher_task


def _health():
    from fastapi import Response
    from main import health

    response = Response()
    return health(response), response.status_code


@pytest.mark.asyncio
async def test_continuous_failure_makes_health_unhealthy(monkeypatch, global_dispatcher):
    import realtime.dispatcher as module

    app, dispatcher = global_dispatcher
    monkeypatch.setattr(module, "POLL_STALE_SECONDS", 0.01)

    def fail():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(dispatcher, "_tick", fail)
    task = asyncio.create_task(dispatcher.run_forever())
    app.state.dispatcher_task = task
    try:
        await asyncio.sleep(0.05)
        assert _health() == ({"status": "error"}, 503)
        assert dispatcher.error_count > 0
    finally:
        dispatcher.request_stop()
        await task
    assert _health() == ({"status": "error"}, 503)


@pytest.mark.asyncio
async def test_health_ok_after_successful_tick(monkeypatch, global_dispatcher):
    app, dispatcher = global_dispatcher
    ticks = 0

    def ok():
        nonlocal ticks
        ticks += 1

    monkeypatch.setattr(dispatcher, "_tick", ok)
    task = asyncio.create_task(dispatcher.run_forever())
    app.state.dispatcher_task = task
    try:
        for _ in range(200):
            if dispatcher.last_success_at is not None:
                break
            await asyncio.sleep(0.005)
        assert ticks >= 1
        assert dispatcher.last_success_at is not None
        assert _health() == ({"status": "ok"}, 200)
    finally:
        dispatcher.request_stop()
        await task


@pytest.mark.asyncio
async def test_health_ok_in_grace_before_first_tick(monkeypatch, global_dispatcher):
    """첫 tick이 아직 성공하기 전(느린 DB)에도 유예 구간 안이면 200이다.
    lifespan처럼 begin_health_window를 task 생성 전에 부르고, task가 첫 실행을 하기도 전에 확인한다."""
    app, dispatcher = global_dispatcher
    def slow():
        # 스레드에서 도는 tick — 끝나기 전에 health를 본다
        import time

        time.sleep(0.1)

    monkeypatch.setattr(dispatcher, "_tick", slow)
    dispatcher.begin_health_window()
    task = asyncio.create_task(dispatcher.run_forever())
    app.state.dispatcher_task = task
    try:
        assert _health() == ({"status": "ok"}, 200)   # task가 아직 돌기 전
        await asyncio.sleep(0.03)
        assert dispatcher.last_success_at is None
        assert _health() == ({"status": "ok"}, 200)   # tick 진행 중, 성공 기록 전
    finally:
        dispatcher.request_stop()
        await task


def test_health_is_503_without_lifespan():
    """lifespan 없이(폴러 task 없음) 부르면 503 — 의도된 동작이다."""
    from main import app

    saved = getattr(app.state, "dispatcher_task", None)
    app.state.dispatcher_task = None
    try:
        assert _health() == ({"status": "error"}, 503)
    finally:
        if saved is None:
            del app.state.dispatcher_task
        else:
            app.state.dispatcher_task = saved


@pytest.mark.asyncio
async def test_run_forever_resets_state_and_cleans_up(monkeypatch):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    d = Dispatcher()
    d.error_count = 7   # 이전 실행의 흔적
    d.last_success_at = 123.0

    def tick():
        assert d.error_count == 0
        assert d.last_success_at is None or d.last_success_at != 123.0
        d.request_stop()

    monkeypatch.setattr(d, "_tick", tick)
    await asyncio.wait_for(d.run_forever(), 1)
    assert d.last_success_at is None and d._health_since is None
    assert d.healthy() is False


@pytest.mark.asyncio
async def test_run_forever_does_not_swallow_cancellation(monkeypatch):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    d = Dispatcher()
    entered = asyncio.Event()

    async def hang(_func):
        entered.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(module.asyncio, "to_thread", hang)
    task = asyncio.create_task(d.run_forever())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert d._started is False and d._health_since is None


@pytest.mark.asyncio
async def test_stop_during_retry_wait_is_immediate(monkeypatch):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 5.0)   # 대기가 길어도 정지는 즉시 먹어야 한다
    monkeypatch.setattr(module, "MAX_RETRY_INTERVAL", 5.0)
    d = Dispatcher()
    task = asyncio.create_task(d.run_forever())
    await asyncio.sleep(0.02)   # 재시도 대기에 들어간 상태
    d.request_stop()
    await asyncio.wait_for(task, 0.5)


# ── #1211: 큐 상한 · 조회 상한 · 스레드 경계 ──


def _rows(n, start=1, map_id="map1"):
    from types import SimpleNamespace

    return [SimpleNamespace(seq=i, map_id=map_id, channel="public", type="x", payload={},
                            recipient_user_id=None) for i in range(start, start + n)]


@pytest.mark.asyncio
async def test_slow_subscriber_is_closed_at_queue_limit_and_others_unaffected(monkeypatch):
    import realtime.dispatcher as module
    from realtime.dispatcher import CLOSED

    monkeypatch.setattr(module, "SUBSCRIBER_QUEUE_MAX", 3)
    d = Dispatcher()
    slow = d.subscribe("map1", channel="public", user_id="u1")
    fast = d.subscribe("map1", channel="public", user_id="u2")

    for row in _rows(10):
        d._deliver([row])
        while not fast.queue.empty():   # 빠른 소비자는 바로 비운다
            fast.queue.get_nowait()
    # 4번째 행에서 넘쳐 evict: 쌓인 3행은 버려지고 CLOSED 하나만 남는다. 이후 행은 더 받지 않는다.
    assert slow not in d._subscribers["map1"]
    assert fast in d._subscribers["map1"]
    items = [slow.queue.get_nowait() for _ in range(slow.queue.qsize())]
    assert items == [CLOSED]                # 스트림이 끝나 클라이언트가 재연결한다

    d._deliver(_rows(1, start=11))
    assert fast.queue.qsize() == 1          # 다른 구독은 계속 받는다


@pytest.mark.asyncio
async def test_full_queue_still_receives_closed_on_member_left(monkeypatch):
    import realtime.dispatcher as module
    from realtime.dispatcher import CLOSED

    monkeypatch.setattr(module, "SUBSCRIBER_QUEUE_MAX", 2)
    d = Dispatcher()
    sub = d.subscribe("map1", channel="public", user_id="u1")
    sub.queue.put_nowait("a")
    sub.queue.put_nowait("b")
    d.close_subscriptions()   # 가득 차 있어도 QueueFull 없이 닫힌다
    assert sub.queue.get_nowait() is CLOSED


def test_tick_returns_rows_without_touching_state(monkeypatch):
    import realtime.dispatcher as module

    d = Dispatcher()
    sub_calls = []
    monkeypatch.setattr(d, "_deliver", lambda rows: sub_calls.append(rows))

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt):
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            assert "LIMIT" in sql.upper()
            from types import SimpleNamespace
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: _rows(2)))

    monkeypatch.setattr(module, "SessionLocal", FakeSession)
    rows = d._tick()
    assert [r.seq for r in rows] == [1, 2]
    assert d._last_seen == 0 and sub_calls == []   # worker thread에서는 전달·상태 변경 없음


def _fake_clock(monkeypatch, d):
    """폴링 텀과 스레드 조회를 가짜로 바꾼다 — 대기 시간을 기다리지 않고 요청된 timeout만 기록한다."""
    import realtime.dispatcher as module

    waits = []

    async def fake_wait_for(aw, timeout):
        waits.append(timeout)
        aw.close()
        if d._stop.is_set():
            return True
        raise asyncio.TimeoutError

    async def fake_to_thread(func, *a):
        return func(*a)

    monkeypatch.setattr(module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)
    return waits


@pytest.mark.asyncio
async def test_backlog_over_row_limit_is_delivered_in_order_without_loss(monkeypatch):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "TICK_ROW_LIMIT", 4)
    monkeypatch.setattr(module, "POLL_INTERVAL", 0.3)
    monkeypatch.setattr(module, "SUBSCRIBER_QUEUE_MAX", 100)
    d = Dispatcher()
    waits = _fake_clock(monkeypatch, d)
    sub = d.subscribe("map1", channel="public", user_id="u1")
    table = _rows(10)
    ticks = []

    def tick():
        rows = [r for r in table if r.seq > d._last_seen][:4]
        ticks.append(len(rows))
        if len(ticks) == 3:
            d.request_stop()
        return rows

    monkeypatch.setattr(d, "_tick", tick)
    await d.run_forever()
    got = [sub.queue.get_nowait().seq for _ in range(sub.queue.qsize())]
    assert got == list(range(1, 11))
    assert ticks == [4, 4, 2]
    assert waits == [0.3, 0, 0]   # 첫 텀 뒤 backlog가 남은 동안은 텀 없이 이어 돈다


@pytest.mark.asyncio
async def test_failure_backoff_starts_from_poll_interval_after_backlog(monkeypatch):
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "TICK_ROW_LIMIT", 2)
    monkeypatch.setattr(module, "POLL_INTERVAL", 1.0)
    monkeypatch.setattr(module, "MAX_RETRY_INTERVAL", 8.0)
    d = Dispatcher()
    waits = _fake_clock(monkeypatch, d)
    # backlog 처리(간격 0) → 실패 4번 → 성공(backlog 없음) → 성공 후 정지
    script = ["backlog", "fail", "fail", "fail", "fail", "ok", "stop"]
    calls = []

    def tick():
        step = script[len(calls)]
        calls.append(step)
        if step == "fail":
            raise RuntimeError("db down")
        if step == "stop":
            d.request_stop()
            return []
        return _rows(2) if step == "backlog" else []

    monkeypatch.setattr(d, "_tick", tick)
    await d.run_forever()
    # 각 tick 앞의 대기: 처음 POLL, backlog 뒤 0, 첫 실패 뒤 POLL×2부터 지수로 MAX까지, 성공하면 POLL로 복귀
    assert waits == [1.0, 0, 2.0, 4.0, 8.0, 8.0, 1.0]
    assert d.error_count == 4


@pytest.mark.asyncio
async def test_subscriber_list_changes_only_on_event_loop_thread(monkeypatch):
    import threading
    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    d = Dispatcher()
    d.subscribe("map1", channel="public", user_id="u1")
    loop_thread = threading.get_ident()
    seen = {}
    orig = d._deliver

    def deliver(rows):
        seen["deliver"] = threading.get_ident()
        orig(rows)

    def tick():
        seen["tick"] = threading.get_ident()
        d.request_stop()
        return _rows(1)

    monkeypatch.setattr(d, "_deliver", deliver)
    monkeypatch.setattr(d, "_tick", tick)
    await asyncio.wait_for(d.run_forever(), 1)
    assert seen["deliver"] == loop_thread      # 전달은 이벤트 루프 스레드
    assert seen["tick"] != loop_thread         # 조회만 worker thread

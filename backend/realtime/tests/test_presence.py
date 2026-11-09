"""지도 접속 상태(#1551) — 시계를 주입해 30초 유예를 sleep 없이 건너뛴다."""

import pytest

from realtime import api
from realtime.dispatcher import Dispatcher
from realtime.presence import GRACE, Presence


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def d(clock):
    dispatcher = Dispatcher()
    dispatcher.presence = Presence(clock)
    return dispatcher


def test_open_connection_is_online_and_counts_a_person_once(d):
    d.subscribe("m1", channel="public", user_id="u1")
    d.subscribe("m1", channel="public", user_id="u1")   # 같은 사람의 두 번째 탭
    assert d.presence.online_user_ids("m1") == {"u1"}
    assert d.presence.online_user_ids("m2") == set()


def test_private_channel_does_not_count_as_online(d):
    d.subscribe("m1", channel="private", user_id="u1")
    assert d.presence.online_user_ids("m1") == set()


def test_two_tabs_one_closes_still_online_both_close_offline_after_grace(d, clock):
    a = d.subscribe("m1", channel="public", user_id="u1")
    b = d.subscribe("m1", channel="public", user_id="u1")
    d.unsubscribe("m1", a)
    clock.now += GRACE * 10
    assert d.presence.online_user_ids("m1") == {"u1"}   # 연결이 하나 남아 있으면 유예와 상관없다
    d.unsubscribe("m1", b)
    assert d.presence.online_user_ids("m1") == {"u1"}   # 마지막 연결이 끊긴 직후는 유예 안
    clock.now += GRACE - 0.1
    assert d.presence.online_user_ids("m1") == {"u1"}
    clock.now += 0.1
    assert d.presence.online_user_ids("m1") == set()


def test_reconnect_within_grace_stays_online_and_is_not_a_change(d, clock):
    sub = d.subscribe("m1", channel="public", user_id="u1")
    d.unsubscribe("m1", sub)
    clock.now += GRACE - 1
    assert d.presence.connect("m1", "u1") is False   # 접속이 끊긴 적이 없다
    clock.now += GRACE * 10
    assert d.presence.expire() == []                   # 유예가 취소됐다
    assert d.presence.online_user_ids("m1") == {"u1"}


def test_connect_reports_change_only_when_going_offline_to_online(clock):
    p = Presence(clock)
    assert p.connect("m1", "u1") is True
    assert p.connect("m1", "u1") is False
    p.disconnect("m1", "u1")
    p.disconnect("m1", "u1")
    clock.now += GRACE
    assert p.expire() == [("m1", "u1")]
    assert p.connect("m1", "u1") is True   # 유예가 끝난 뒤의 연결은 새 접속


def test_unsubscribe_twice_does_not_double_count(d, clock):
    keep = d.subscribe("m1", channel="public", user_id="u1")
    gone = d.subscribe("m1", channel="public", user_id="u1")
    d.unsubscribe("m1", gone)
    d.unsubscribe("m1", gone)
    clock.now += GRACE * 10
    assert d.presence.online_user_ids("m1") == {"u1"}
    d.unsubscribe("m1", keep)


def test_api_online_user_ids_reads_the_dispatcher(monkeypatch, d):
    import realtime.api as module

    monkeypatch.setattr(module, "dispatcher", d)
    d.subscribe("m1", channel="public", user_id="u1")
    assert api.online_user_ids("m1") == {"u1"}
    assert api.online_user_ids("other") == set()


# ── member.presence 이벤트(#1551) ──


def _drain(sub):
    items = []
    while not sub.queue.empty():
        items.append(sub.queue.get_nowait())
    return [(i.type, i.payload) for i in items]


def test_first_connection_announces_online_to_public_subscribers_including_itself(d):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    _drain(watcher)
    me = d.subscribe("m1", channel="public", user_id="u1")
    assert _drain(me) == [("member.presence", {"user_id": "u1", "online": True})]   # 자기 이벤트도 온다
    assert _drain(watcher) == [("member.presence", {"user_id": "u1", "online": True})]


def test_second_tab_and_private_channel_announce_nothing(d):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    d.subscribe("m1", channel="public", user_id="u1")
    _drain(watcher)
    d.subscribe("m1", channel="public", user_id="u1")
    d.subscribe("m1", channel="private", user_id="u3")
    assert _drain(watcher) == []


def test_presence_stays_inside_its_map_and_never_reaches_private_channel(d):
    other_map = d.subscribe("m2", channel="public", user_id="u9")
    private = d.subscribe("m1", channel="private", user_id="u2")
    _drain(other_map)   # 자기 접속 알림은 뺀다
    d.subscribe("m1", channel="public", user_id="u1")
    assert _drain(other_map) == []
    assert _drain(private) == []   # 개인 채널 구독자에게 새지 않는다


def test_two_tabs_one_closes_no_event_both_close_false_after_grace(d, clock):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    a = d.subscribe("m1", channel="public", user_id="u1")
    b = d.subscribe("m1", channel="public", user_id="u1")
    _drain(watcher)
    d.unsubscribe("m1", a)
    clock.now += GRACE * 2
    d.expire_presence()
    assert _drain(watcher) == []                      # 한 탭이 남아 있다
    d.unsubscribe("m1", b)
    clock.now += GRACE - 0.1
    d.expire_presence()
    assert _drain(watcher) == []                      # 유예 안
    clock.now += 0.1
    d.expire_presence()
    assert _drain(watcher) == [("member.presence", {"user_id": "u1", "online": False})]
    d.expire_presence()
    assert _drain(watcher) == []                      # 한 번만 보낸다


def test_reconnect_within_grace_sends_no_event(d, clock):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    gone = d.subscribe("m1", channel="public", user_id="u1")
    _drain(watcher)
    d.unsubscribe("m1", gone)
    clock.now += GRACE - 1
    d.subscribe("m1", channel="public", user_id="u1")
    clock.now += GRACE * 10
    d.expire_presence()
    assert _drain(watcher) == []


def test_presence_is_sse_without_id_and_not_stored():
    from realtime.dispatcher import PresenceEvent
    from realtime.router import _sse_format

    text = _sse_format(PresenceEvent(map_id="m1", payload={"user_id": "u1", "online": True}))
    assert text == 'event: member.presence\ndata: {"user_id": "u1", "online": true}\n\n'   # id 줄 없음


@pytest.mark.asyncio
async def test_other_member_joining_reaches_open_public_stream_as_presence_chunk():
    import asyncio

    from auth.schemas import CurrentUser
    from realtime.dispatcher import dispatcher
    from realtime.router import public_events

    class Alive:
        async def is_disconnected(self):
            return False

    async def open_stream(user_id):
        response = await public_events(request=Alive(), mapId="pres-map", user=CurrentUser(user_id=user_id),
                                       last_event_id=None)
        agen = response.body_iterator
        assert "ping" in await asyncio.wait_for(agen.__anext__(), timeout=1)
        pending = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0)
        return agen, pending

    a, a_pending = await open_stream("user-a")
    own = await asyncio.wait_for(a_pending, timeout=1)   # 자기 자신의 접속도 온다(화면이 거른다)
    assert own == 'event: member.presence\ndata: {"user_id": "user-a", "online": true}\n\n'
    a_pending = asyncio.ensure_future(a.__anext__())
    b, b_pending = await open_stream("user-b")
    try:
        chunk = await asyncio.wait_for(a_pending, timeout=1)
        assert chunk == 'event: member.presence\ndata: {"user_id": "user-b", "online": true}\n\n'
    finally:
        for agen, pending in ((a, a_pending), (b, b_pending)):
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await agen.aclose()
    assert dispatcher._subscribers.get("pres-map") is None

def test_connect_after_grace_ended_but_before_expire_is_a_new_online(clock):
    p = Presence(clock)
    p.connect("m1", "u1")
    p.disconnect("m1", "u1")
    clock.now += GRACE + 1   # expire가 아직 안 돌았다
    assert p.connect("m1", "u1") is True


def test_loop_expires_presence_each_cycle(monkeypatch):
    import asyncio

    import realtime.dispatcher as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.001)
    d = Dispatcher()
    calls = []
    monkeypatch.setattr(d.presence, "expire", lambda: calls.append(1) or [])

    def tick():
        d.request_stop()
        return []

    monkeypatch.setattr(d, "_tick", tick)
    asyncio.run(asyncio.wait_for(d.run_forever(), 1))
    assert calls   # 운영 루프가 expire를 부른다


def test_readers_in_other_threads_never_see_dict_changed_during_iteration():
    import threading

    p = Presence()
    stop = threading.Event()
    errors = []

    def reader():
        try:
            while not stop.is_set():
                p.online_user_ids("m1")
        except Exception as exc:   # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(2)]
    for t in threads:
        t.start()
    try:
        for i in range(20000):   # 이벤트 루프 쪽 쓰기를 흉내 낸다
            user = f"u{i % 50}"
            p.connect("m1", user)
            p.disconnect("m1", user)
            if i % 100 == 0:
                p.expire()
    finally:
        stop.set()
        for t in threads:
            t.join()
    assert errors == []


# ── 후속(#1551): 나가기·탈퇴, 만료 뒤 재연결, 종료 중 구독, 실제 순서 ──


def test_member_left_drops_presence_without_grace_and_without_offline_event(d, clock):
    from types import SimpleNamespace

    watcher = d.subscribe("m1", channel="public", user_id="u2")
    leaver = d.subscribe("m1", channel="public", user_id="u1")
    _drain(watcher)
    row = SimpleNamespace(seq=1, map_id="m1", channel="public", type="member.left",
                          payload={"map_id": "m1", "user_id": "u1", "new_owner_user_id": None},
                          recipient_user_id=None)
    d._deliver([row])
    assert d.presence.online_user_ids("m1") == {"u2"}   # 유예 없이 바로 빠진다
    assert [t for t, _ in _drain(watcher)] == ["member.left"]
    d.unsubscribe("m1", leaver)   # 늦게 끝나는 옛 연결
    clock.now += GRACE * 10
    d.expire_presence()
    assert _drain(watcher) == []   # offline 이벤트 없음


def test_old_connection_closing_late_does_not_cut_a_new_connection_of_the_same_user(d, clock):
    from types import SimpleNamespace

    old = d.subscribe("m1", channel="public", user_id="u1")
    d._deliver([SimpleNamespace(seq=1, map_id="m1", channel="public", type="member.left",
                                payload={"map_id": "m1", "user_id": "u1"}, recipient_user_id=None)])
    new = d.subscribe("m1", channel="public", user_id="u1")   # 다시 들어와 곧바로 붙음
    d.unsubscribe("m1", old)                                   # 옛 연결이 뒤늦게 끝남
    clock.now += GRACE * 10
    d.expire_presence()
    assert d.presence.online_user_ids("m1") == {"u1"}
    d.unsubscribe("m1", new)


def test_map_deleted_drops_the_whole_map_from_presence(d, clock):
    from types import SimpleNamespace

    a = d.subscribe("m1", channel="public", user_id="u1")
    b = d.subscribe("m1", channel="public", user_id="u2")
    d._deliver([SimpleNamespace(seq=1, map_id="m1", channel="public", type="map.deleted",
                                payload={"map_id": "m1"}, recipient_user_id=None)])
    assert d.presence.online_user_ids("m1") == set()
    d.unsubscribe("m1", a)
    d.unsubscribe("m1", b)
    clock.now += GRACE * 10
    assert d.presence.expire() == []   # 지도가 사라진 뒤 유예 표에 남지 않는다


def test_reconnect_after_grace_ended_but_before_expire_sends_false_then_true(d, clock):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    gone = d.subscribe("m1", channel="public", user_id="u1")
    _drain(watcher)
    d.unsubscribe("m1", gone)
    clock.now += GRACE + 1   # 유예가 끝났지만 폴링 루프가 아직 expire를 안 돌렸다
    d.subscribe("m1", channel="public", user_id="u1")
    assert _drain(watcher) == [
        ("member.presence", {"user_id": "u1", "online": False}),
        ("member.presence", {"user_id": "u1", "online": True}),
    ]


def test_subscription_made_while_closing_is_not_counted_as_online(d):
    d.close_subscriptions()
    sub = d.subscribe("m1", channel="public", user_id="u1")
    assert d.presence.online_user_ids("m1") == set()
    d.unsubscribe("m1", sub)
    assert d.presence.online_user_ids("m1") == set()   # 짝이 맞아 유예도 생기지 않는다


def test_closing_subscription_does_not_cut_another_counted_connection(d):
    live = d.subscribe("m1", channel="public", user_id="u1")
    d.close_subscriptions()
    late = d.subscribe("m1", channel="public", user_id="u1")   # 종료 중이라 세지 않는다
    d.unsubscribe("m1", late)
    assert d.presence.online_user_ids("m1") == {"u1"}          # live의 연결 수는 그대로
    d.unsubscribe("m1", live)


@pytest.mark.asyncio
async def test_real_stream_order_replay_then_own_presence_then_live_and_member_left(db_session, monkeypatch):
    """재전송 뒤 첫 live 이벤트는 자기 member.presence, member.left 뒤 그 사람의 유예 offline은 오지 않는다."""
    import asyncio

    import realtime.router as router_module
    from auth.schemas import CurrentUser
    from common.events import EventLog
    from realtime.dispatcher import dispatcher
    from realtime.router import public_events

    class _Ctx:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(router_module, "SessionLocal", lambda: _Ctx())
    clk = Clock()
    monkeypatch.setattr(dispatcher, "presence", Presence(clk))

    old = EventLog(map_id="order-map", channel="public", type="pin.created", payload={"n": 1})
    db_session.add(old)
    db_session.flush()
    replayed = EventLog(map_id="order-map", channel="public", type="pin.updated", payload={"n": 2})
    db_session.add(replayed)
    db_session.flush()

    class Alive:
        async def is_disconnected(self):
            return False

    async def chunk(agen):
        return await asyncio.wait_for(agen.__anext__(), timeout=1)

    resp_b = await public_events(request=Alive(), mapId="order-map", user=CurrentUser(user_id="user-b"),
                                 last_event_id=str(old.seq))
    b = resp_b.body_iterator
    assert "ping" in await chunk(b)                     # 연결 직후 ping
    assert "pin.updated" in await chunk(b)              # 재전송
    own = await chunk(b)                                # 구독 뒤 첫 live 이벤트는 자기 접속
    assert own == 'event: member.presence\ndata: {"user_id": "user-b", "online": true}\n\n'.replace("\n", "\n")

    resp_a = await public_events(request=Alive(), mapId="order-map", user=CurrentUser(user_id="user-a"),
                                 last_event_id=None)
    a = resp_a.body_iterator
    assert "ping" in await chunk(a)
    await chunk(a)                                      # a의 자기 접속
    assert '"user-a"' in await chunk(b)                 # b가 a의 접속을 받는다

    left = EventLog(seq=None, map_id="order-map", channel="public", type="member.left",
                    payload={"map_id": "order-map", "user_id": "user-a", "new_owner_user_id": None})
    left.seq = 10**9
    dispatcher._deliver([left])
    assert "member.left" in await chunk(b)
    assert "member.left" in await chunk(a)              # a도 자기 member.left를 먼저 받고
    with pytest.raises(StopAsyncIteration):             # 그 뒤 스트림이 닫힌다
        await chunk(a)
    assert dispatcher.presence.online_user_ids("order-map") == {"user-b"}   # 유예 없이 바로 빠진다
    clk.now += GRACE * 10
    dispatcher.expire_presence()
    with pytest.raises(asyncio.TimeoutError):           # 나간 사람의 offline은 오지 않는다
        await asyncio.wait_for(b.__anext__(), timeout=0.1)
    await b.aclose()

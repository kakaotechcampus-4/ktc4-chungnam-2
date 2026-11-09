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


def test_first_connection_announces_online_to_other_public_subscribers_not_itself(d):
    watcher = d.subscribe("m1", channel="public", user_id="u2")
    _drain(watcher)
    me = d.subscribe("m1", channel="public", user_id="u1")
    assert _drain(me) == []   # 방금 붙은 연결은 REST 구성원 목록으로 현황을 받는다
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
    b, b_pending = await open_stream("user-b")
    try:
        chunk = await asyncio.wait_for(a_pending, timeout=1)
        assert chunk == 'event: member.presence\ndata: {"user_id": "user-b", "online": true}\n\n'
        assert not b_pending.done()   # 방금 붙은 연결에는 보내지 않는다
    finally:
        for agen, pending in ((a, a_pending), (b, b_pending)):
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await agen.aclose()
    assert dispatcher._subscribers.get("pres-map") is None

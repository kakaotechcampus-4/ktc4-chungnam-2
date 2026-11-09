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

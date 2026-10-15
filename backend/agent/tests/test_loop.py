"""개발용 반복 작업(12.1) — 기본값(False)이면 띄우지 않고, 켜면 주기마다 run_tick을 부르고 정지 신호로 멈춘다."""

import asyncio

from agent import constants, flows, loop


def test_default_off_starts_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(flows, "run_tick", lambda now: calls.append(now))

    async def main():
        loop.start()
        await asyncio.sleep(0.05)
        await loop.stop(1.0)

    asyncio.run(main())

    assert constants.AGENT_LOOP_IN_PROCESS is False
    assert calls == []


def test_on_runs_tick_until_stopped(monkeypatch):
    calls = []
    monkeypatch.setattr(constants, "AGENT_LOOP_IN_PROCESS", True)
    monkeypatch.setattr(constants, "TICK_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(flows, "run_tick", lambda now: calls.append(now))

    async def main():
        loop.start()
        await asyncio.sleep(0.2)
        await loop.stop(1.0)
        stopped_at = len(calls)
        await asyncio.sleep(0.05)
        return stopped_at

    stopped_at = asyncio.run(main())

    assert stopped_at >= 1
    assert len(calls) == stopped_at   # 멈춘 뒤에는 부르지 않는다
    assert all(c.tzinfo is not None for c in calls)


def test_failing_tick_does_not_stop_the_loop(monkeypatch):
    calls = []
    monkeypatch.setattr(constants, "AGENT_LOOP_IN_PROCESS", True)
    monkeypatch.setattr(constants, "TICK_INTERVAL_SEC", 0.01)

    def boom(now):
        calls.append(now)
        raise RuntimeError("tick 실패")

    monkeypatch.setattr(flows, "run_tick", boom)

    async def main():
        loop.start()
        await asyncio.sleep(0.2)
        await loop.stop(1.0)

    asyncio.run(main())

    assert len(calls) >= 2

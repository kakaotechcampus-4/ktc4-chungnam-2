"""개발용 관찰 반복 작업(docs/agent-v2.md 12.1). `AGENT_LOOP_IN_PROCESS=True`일 때만 lifespan에서 띄워
`TICK_INTERVAL_SEC`마다 `flows.run_tick`을 부른다. 배포는 Cloud Scheduler → `POST /internal/agent/tick`(M1)이다.

main.py lifespan은 `start()`와 `stop()`만 부른다. 종료 순서(#130)는 agent 정지 대기 → dispatcher 정지 → SSE 정리 →
연결 풀 닫기다. realtime/dispatcher.py처럼 취소가 아니라 정지 신호로 멈춰, 스레드에서 도는 tick이 끝난 뒤에 풀이
닫히게 한다.
"""

import asyncio
import logging
from datetime import datetime, timezone

from agent import constants, flows

log = logging.getLogger("pingo.agent")

_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None


def start() -> None:
    """lifespan 시작에서 부른다. AGENT_LOOP_IN_PROCESS가 False(기본)면 아무것도 하지 않는다."""
    global _task, _stop
    if not constants.AGENT_LOOP_IN_PROCESS or _task is not None:
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_run_forever(_stop))
    log.info("agent 관찰 반복 작업 시작(%d초마다)", constants.TICK_INTERVAL_SEC)


async def stop(timeout: float) -> None:
    """lifespan 종료에서 dispatcher를 멈추기 전에 부른다. 진행 중인 tick은 끝까지 돌게 두고 기다린다. timeout을
    넘기면 취소한다(wait_for). 띄우지 않았으면 바로 돌아온다."""
    global _task, _stop
    task, stop_event = _task, _stop
    _task, _stop = None, None
    if task is None:
        return
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout)
    except asyncio.TimeoutError:
        log.warning("agent 관찰 반복 작업이 %s초 안에 멈추지 않아 취소했다", timeout)
    except Exception as exc:
        log.error("agent 관찰 반복 작업 종료 중 오류 error=%s", type(exc).__name__)


async def _run_forever(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            # sleep 대신 정지 신호를 기다린다 — 신호가 오면 주기를 채우지 않고 바로 깬다
            await asyncio.wait_for(stop_event.wait(), constants.TICK_INTERVAL_SEC)
            break
        except asyncio.TimeoutError:
            pass
        try:
            # 동기 DB 작업이라 이벤트 루프를 막지 않게 스레드로 넘긴다
            await asyncio.to_thread(flows.run_tick, datetime.now(timezone.utc))
        except Exception as exc:   # 한 번 실패해도 다음 주기에 다시 돈다
            log.error("agent run_tick 실패 error=%s", type(exc).__name__)

"""asyncio 폴링 루프 + map_id별 in-memory 구독자 큐. lifespan에서 시작·종료한다."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from common.database import SessionLocal
from common.events import EventLog
from realtime.core import advance, close_after

POLL_INTERVAL = 0.5

# 종료 신호 — 구독 큐에 이 값이 들어오면 SSE 제너레이터는 스스로 빠져나온다(서버 종료, 또는
# map.deleted·member.left 뒤 구독 끊기 — docs/events.md "구독을 끊는 경우").
# 큐에 행이 아닌 값을 섞는 대신 모듈 전용 sentinel 하나만 쓴다(router가 `is CLOSED`로 비교).
CLOSED = object()


@dataclass(frozen=True)
class Subscription:
    """구독 하나가 무엇을 받을 자격이 있는지 — 이 조건을 큐에 넣는 시점에 검사한다.
    channel="private"이면 user_id와 행의 recipient_user_id가 일치할 때만 받는다. user_id는 전체
    채널에서도 기억한다 — 받을 자격이 아니라 member.left 뒤 누구의 구독을 닫을지 가리는 데 쓴다."""

    channel: str            # "public" | "private"
    user_id: str            # 구독한 사람(두 채널 모두)
    queue: "asyncio.Queue" = field(default_factory=asyncio.Queue)

    def wants(self, row: EventLog) -> bool:
        if row.channel != self.channel:
            return False
        if self.channel == "private" and row.recipient_user_id != self.user_id:
            return False
        return True


class Dispatcher:
    def __init__(self):
        self._subscribers: dict[str, list[Subscription]] = {}
        self._last_seen = 0
        self._gap_since: dict[int, datetime] = {}
        self._started = False   # run_forever 중복 시작 방지
        # run_forever 정지 신호 — 취소가 아니라 이걸로 멈춘다. Event는 run_forever 안에서(실행 중인
        # 루프에서) 새로 만든다: 싱글턴이 import 시점에 만든 Event를 TestClient마다 다른 루프가
        # 넘나들며 재사용하지 않게 한다.
        self._stop: asyncio.Event | None = None
        self._stop_requested = False   # run_forever가 Event를 만들기 전에 온 정지 요청 보관
        self._closing = False   # 종료 중이면 새 구독도 곧바로 닫힌 채로 내준다

    def initialize_last_seen(self) -> None:
        """기동 시 한 번 호출 — lifespan에서 run_forever보다 먼저 부른다.
        0부터 시작하면 이미 존재하는 모든 과거 이벤트를 '새 이벤트'로 오인해 전부 다시
        내보내려 시도한다(그리고 오래된 것들은 구멍으로 취급돼 혼란만 커짐)."""
        with SessionLocal() as db:
            self._last_seen = db.execute(select(func.coalesce(func.max(EventLog.seq), 0))).scalar_one()

    def subscribe(self, map_id: str, *, channel: str, user_id: str) -> Subscription:
        sub = Subscription(channel=channel, user_id=user_id)
        self._subscribers.setdefault(map_id, []).append(sub)
        if self._closing:
            sub.queue.put_nowait(CLOSED)
        return sub

    def request_stop(self) -> None:
        """폴링 루프에 정지를 요청한다. 진행 중인 _tick은 끊지 않고 끝까지 돈 뒤 루프가 빠져나온다
        (스레드에서 도는 DB 조회를 취소하면 그 직후 엔진을 닫을 때 조회가 깨진다)."""
        self._stop_requested = True
        if self._stop is not None:
            self._stop.set()

    def finish_shutdown(self) -> None:
        """종료가 전부 끝난 시점(lifespan 마지막)에 부른다 — 싱글턴에 닫힘 상태를 남기지 않는다.
        남기면 같은 프로세스의 다음 lifespan/테스트가 이미 닫힌 구독을 받는다."""
        self._closing = False

    def close_subscriptions(self) -> None:
        """열려 있는 모든 SSE 구독을 깨워 스스로 종료하게 한다 — `await sub.queue.get()` 대기 해제."""
        self._closing = True
        for subs in self._subscribers.values():
            for sub in subs:
                sub.queue.put_nowait(CLOSED)

    def unsubscribe(self, map_id: str, sub: Subscription) -> None:
        # list.remove()는 이미 없는 항목이면 ValueError를 던져 finally 블록에서 원래 예외를
        # 가릴 수 있다. 없으면 조용히 넘어간다(discard 방식).
        subs = self._subscribers.get(map_id)
        if subs is None:
            return
        try:
            subs.remove(sub)
        except ValueError:
            pass
        if not subs:
            self._subscribers.pop(map_id, None)   # 빈 리스트를 계속 안 들고 있는다

    async def run_forever(self) -> None:
        if self._started:
            raise RuntimeError("Dispatcher.run_forever()는 두 번 시작할 수 없다")
        self._started = True
        stop = self._stop = asyncio.Event()
        if self._stop_requested:
            stop.set()
        try:
            while not stop.is_set():
                try:
                    # sleep 대신 정지 신호를 기다린다 — 신호가 오면 폴링 텀을 안 채우고 바로 깬다.
                    await asyncio.wait_for(stop.wait(), POLL_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    pass
                # 동기 DB 쿼리를 async 루프 안에서 그대로 부르면 그 500ms 폴링 텀마다 이벤트 루프
                # 전체(다른 SSE 연결 포함)가 DB 왕복 시간만큼 멈춘다. 스레드로 넘긴다.
                await asyncio.to_thread(self._tick)
        finally:
            # 같은 프로세스에서 lifespan이 다시 돌 수 있다(테스트의 여러 TestClient 등).
            self._started = False
            self._stop = None
            self._stop_requested = False

    def _tick(self) -> None:
        with SessionLocal() as db:
            rows = db.execute(
                select(EventLog).where(EventLog.seq > self._last_seen).order_by(EventLog.seq)
            ).scalars().all()
        emit, self._last_seen, self._gap_since = advance(
            self._last_seen, rows, datetime.now(timezone.utc), self._gap_since
        )
        self._deliver(emit)

    def _deliver(self, rows) -> None:
        """행마다 받을 구독에 넣고, 그 행이 구독을 끊는 행이면 해당 구독에 CLOSED를 넣는다.
        이벤트가 CLOSED보다 먼저 큐에 들어가야 받은 쪽이 왜 끊겼는지 안다(docs/events.md)."""
        for row in rows:
            subs = list(self._subscribers.get(row.map_id, []))
            for sub in subs:
                if sub.wants(row):
                    sub.queue.put_nowait(row)
            scope = close_after(row)
            if scope is None:
                continue
            for sub in subs:
                if scope.covers(sub.user_id):
                    sub.queue.put_nowait(CLOSED)


dispatcher = Dispatcher()

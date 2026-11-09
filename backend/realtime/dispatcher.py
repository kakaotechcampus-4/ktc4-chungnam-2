"""asyncio 폴링 루프 + map_id별 in-memory 구독자 큐. lifespan에서 시작·종료한다."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from common.database import SessionLocal
from common.events import EventLog
from realtime.core import advance, close_after
from realtime.presence import Presence

POLL_INTERVAL = 0.5
MAX_RETRY_INTERVAL = 8.0
POLL_STALE_SECONDS = 30.0
# 한 tick이 가져오는 행 수 상한 — 이벤트가 몰려도 한 번에 큰 결과를 들지 않는다. 남은 행은 마지막으로
# 처리한 seq 뒤부터 다음 tick이 이어서 가져온다(순서·누락 없음).
TICK_ROW_LIMIT = 500
# 구독 큐 상한 — 소비가 느린 연결(끊긴 모바일 등)에 메모리가 끝없이 쌓이지 않게 한다. 넘치면 그 구독만
# 끊고, 클라이언트가 Last-Event-ID로 재연결해 재전송(24h)·REST 재조회로 따라잡는다(docs/events.md 3·5번).
SUBSCRIBER_QUEUE_MAX = 1000
logger = logging.getLogger("pingo.realtime")

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
    queue: "asyncio.Queue" = field(default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX))

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
        self.error_count = 0
        self.last_success_at: float | None = None  # monotonic clock
        self._health_since: float | None = None
        self.presence = Presence()   # 지도 접속 상태(#1551) — 전체 채널 구독 수로 센다
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
        if channel == "public":
            self.presence.connect(map_id, user_id)
        if self._closing:
            self._close(sub)
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
            for sub in list(subs):
                self._close(sub)

    @staticmethod
    def _close(sub: Subscription) -> None:
        """구독 큐에 CLOSED를 넣는다. 큐가 가득 찼으면 쌓인 행을 버리고 넣는다 — 어차피 끊을 구독이고,
        받은 쪽은 마지막으로 받은 id로 재연결해 따라잡는다."""
        if sub.queue.full():
            while not sub.queue.empty():
                sub.queue.get_nowait()
        sub.queue.put_nowait(CLOSED)

    def _evict(self, map_id: str, sub: Subscription) -> None:
        """큐가 넘친 구독을 끊는다 — 구독 목록에서 빼고 CLOSED로 스트림을 끝낸다."""
        self._close(sub)
        self.unsubscribe(map_id, sub)
        logger.warning("subscription closed: queue full map_id=%s channel=%s", map_id, sub.channel)

    def unsubscribe(self, map_id: str, sub: Subscription) -> None:
        # list.remove()는 이미 없는 항목이면 ValueError를 던져 finally 블록에서 원래 예외를
        # 가릴 수 있다. 없으면 조용히 넘어간다(discard 방식).
        subs = self._subscribers.get(map_id)
        if subs is None:
            return
        try:
            subs.remove(sub)
        except ValueError:
            return   # 이미 뺀 구독 — 접속 수를 두 번 줄이지 않는다
        if sub.channel == "public":
            self.presence.disconnect(map_id, sub.user_id)
        if not subs:
            self._subscribers.pop(map_id, None)   # 빈 리스트를 계속 안 들고 있는다

    def begin_health_window(self) -> None:
        """health 상태를 동기로 초기화한다 — lifespan이 task를 만들기 전에 부른다. task 첫 실행 전에
        /health가 불려도 시작 시각이 이미 있어 오탐 503이 나지 않는다(run_forever도 없으면 스스로 부른다)."""
        self.error_count = 0
        self.last_success_at = None
        self._health_since = time.monotonic()

    def healthy(self) -> bool:
        # 시작 시각(_health_since)이 있어야 한다 — begin_health_window가 기록하고 run_forever 종료 때 지운다.
        reference = self.last_success_at if self.last_success_at is not None else self._health_since
        return reference is not None and time.monotonic() - reference <= POLL_STALE_SECONDS

    async def run_forever(self) -> None:
        if self._started:
            raise RuntimeError("Dispatcher.run_forever()는 두 번 시작할 수 없다")
        self._started = True
        if self._health_since is None:   # lifespan이 미리 기록하지 않은 경우(직접 호출)
            self.begin_health_window()
        retry_interval = POLL_INTERVAL
        stop = self._stop = asyncio.Event()
        if self._stop_requested:
            stop.set()
        try:
            while not stop.is_set():
                try:
                    # sleep 대신 정지 신호를 기다린다 — 신호가 오면 폴링 텀을 안 채우고 바로 깬다.
                    await asyncio.wait_for(stop.wait(), retry_interval)
                    break
                except asyncio.TimeoutError:
                    pass
                self.presence.expire()   # 끊긴 지 GRACE가 지난 접속 기록을 치운다(이벤트로 알리는 일은 다음 PR)
                # 동기 DB 쿼리를 async 루프 안에서 그대로 부르면 그 500ms 폴링 텀마다 이벤트 루프
                # 전체(다른 SSE 연결 포함)가 DB 왕복 시간만큼 멈춘다. 조회만 스레드로 넘기고, 구독 큐와
                # 구독 목록은 이벤트 루프(여기)에서만 만진다 — asyncio 객체는 스레드에서 만지지 않는다.
                try:
                    rows = await asyncio.to_thread(self._tick)
                    backlog = self._process(rows or [])
                except Exception as exc:  # noqa: BLE001
                    self.error_count += 1
                    logger.warning("dispatcher tick failed: %s", type(exc).__name__)
                    # backlog 직후라 간격이 0이어도 실패 백오프는 POLL_INTERVAL부터 시작한다(0×2=0 방지, #1200).
                    retry_interval = min(max(retry_interval, POLL_INTERVAL) * 2, MAX_RETRY_INTERVAL)
                else:
                    self.last_success_at = time.monotonic()
                    retry_interval = 0 if backlog else POLL_INTERVAL   # 남은 행은 텀 없이 이어서
                    await asyncio.sleep(0)   # 텀이 0이어도 SSE 전송 task들이 큐를 비울 차례를 준다
        finally:
            # 같은 프로세스에서 lifespan이 다시 돌 수 있다(테스트의 여러 TestClient 등).
            self._started = False
            self.last_success_at = None
            self._health_since = None   # 멈춘 폴러는 healthy()가 False
            self._stop = None
            self._stop_requested = False

    def _tick(self) -> list:
        """worker thread에서 돈다 — DB 조회 결과(행 목록)만 돌려주고 dispatcher 상태는 바꾸지 않는다.
        _last_seen은 이벤트 루프만 쓰고, 루프는 이 조회를 기다리는 동안 쓰지 않는다."""
        with SessionLocal() as db:
            return list(db.execute(
                select(EventLog).where(EventLog.seq > self._last_seen)
                .order_by(EventLog.seq).limit(TICK_ROW_LIMIT)
            ).scalars().all())

    def _process(self, rows: list) -> bool:
        """이벤트 루프에서 조회 결과를 처리한다. 상한만큼 가득 가져왔고 그중 일부라도 진행했으면 True
        (바로 다음 tick을 돌린다). 구멍 대기로 진행이 없으면 False라 텀을 두고 기다린다."""
        before = self._last_seen
        emit, self._last_seen, self._gap_since = advance(
            before, rows, datetime.now(timezone.utc), self._gap_since
        )
        self._deliver(emit)
        return len(rows) >= TICK_ROW_LIMIT and self._last_seen > before

    def _deliver(self, rows) -> None:
        """행마다 받을 구독에 넣고, 그 행이 구독을 끊는 행이면 해당 구독에 CLOSED를 넣는다.
        이벤트가 CLOSED보다 먼저 큐에 들어가야 받은 쪽이 왜 끊겼는지 안다(docs/events.md)."""
        for row in rows:
            subs = list(self._subscribers.get(row.map_id, []))
            for sub in subs:
                if sub.wants(row):
                    try:
                        sub.queue.put_nowait(row)
                    except asyncio.QueueFull:
                        self._evict(row.map_id, sub)
            scope = close_after(row)
            if scope is None:
                continue
            for sub in subs:
                if scope.covers(sub.user_id):
                    self._close(sub)


dispatcher = Dispatcher()

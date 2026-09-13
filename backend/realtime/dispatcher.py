"""asyncio 폴링 루프 + map_id별 in-memory 구독자 큐. lifespan에서 시작·종료한다."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from common.database import SessionLocal
from common.events import EventLog
from realtime.core import advance

POLL_INTERVAL = 0.5


@dataclass(frozen=True)
class Subscription:
    """구독 하나가 무엇을 받을 자격이 있는지 — 이 조건을 큐에 넣는 시점에 검사한다.
    channel="public"이면 user_id는 의미 없다(전체 공개). channel="private"이면 user_id와
    행의 recipient_user_id가 일치할 때만 받는다."""

    channel: str            # "public" | "private"
    user_id: str | None     # channel="private"일 때만 사용
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

    def initialize_last_seen(self) -> None:
        """기동 시 한 번 호출 — lifespan에서 run_forever보다 먼저 부른다.
        0부터 시작하면 이미 존재하는 모든 과거 이벤트를 '새 이벤트'로 오인해 전부 다시
        내보내려 시도한다(그리고 오래된 것들은 구멍으로 취급돼 혼란만 커짐)."""
        with SessionLocal() as db:
            self._last_seen = db.execute(select(func.coalesce(func.max(EventLog.seq), 0))).scalar_one()

    def subscribe(self, map_id: str, *, channel: str, user_id: str | None = None) -> Subscription:
        sub = Subscription(channel=channel, user_id=user_id)
        self._subscribers.setdefault(map_id, []).append(sub)
        return sub

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
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            # 동기 DB 쿼리를 async 루프 안에서 그대로 부르면 그 500ms 폴링 텀마다 이벤트 루프
            # 전체(다른 SSE 연결 포함)가 DB 왕복 시간만큼 멈춘다. 스레드로 넘긴다.
            await asyncio.to_thread(self._tick)

    def _tick(self) -> None:
        with SessionLocal() as db:
            rows = db.execute(
                select(EventLog).where(EventLog.seq > self._last_seen).order_by(EventLog.seq)
            ).scalars().all()
        emit, self._last_seen, self._gap_since = advance(
            self._last_seen, rows, datetime.now(timezone.utc), self._gap_since
        )
        for row in emit:
            for sub in self._subscribers.get(row.map_id, []):
                if sub.wants(row):
                    sub.queue.put_nowait(row)


dispatcher = Dispatcher()

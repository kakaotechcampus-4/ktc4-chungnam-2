"""Last-Event-ID 재연결 재전송. 실시간 tail과 같은 event_log 테이블·같은 정렬 기준을
쓴다 — 재연결 경로에는 core.advance의 seq 재정렬 위험이 없다(이미 다 커밋된 구간이므로)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.events import EventLog

RETENTION = timedelta(hours=24)


@dataclass(frozen=True)
class ReplayResult:
    rows: list[EventLog]
    truncated: bool   # after_seq가 보존기간보다 오래돼 일부(또는 전부) 못 돌려줬다


def replay(db: Session, map_id: str, after_seq: int, channel: str) -> ReplayResult:
    cutoff = datetime.now(timezone.utc) - RETENTION
    # after_seq 시점 자체가 이미 보존기간 밖인지 별도로 확인한다 — 24시간 전에 커밋된 seq를
    # 가진 행을 하나 찾아서 after_seq가 그보다 작으면 이미 잘려나간 구간이 있다는 뜻.
    oldest_kept = db.execute(
        select(func.min(EventLog.seq)).where(EventLog.created_at >= cutoff)
    ).scalar_one_or_none()
    truncated = oldest_kept is not None and after_seq < oldest_kept - 1
    rows = db.execute(
        select(EventLog)
        .where(EventLog.map_id == map_id, EventLog.channel == channel,
               EventLog.seq > after_seq, EventLog.created_at >= cutoff)
        .order_by(EventLog.seq)
    ).scalars().all()
    return ReplayResult(rows=list(rows), truncated=truncated)

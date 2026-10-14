"""Last-Event-ID 재연결 재전송. 실시간 tail과 같은 event_log 테이블·같은 정렬 기준을
쓴다 — 재연결 경로에는 core.advance의 seq 재정렬 위험이 없다(이미 다 커밋된 구간이므로)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
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


def latest_seq_by_map(db: Session) -> dict[str, tuple[int, datetime]]:
    """지도별 가장 큰 event_log seq와 그 행의 created_at(#522, 커서 개정 #525). 보존기간(replay와 같은
    cutoff) 안의 행만, 두 채널 모두 본다. 쿼리 한 번 — map_id마다 seq가 가장 큰 행 하나(DISTINCT ON).
    번호와 시각만 돌려주고 type·payload·수신자는 내보내지 않는다."""
    cutoff = datetime.now(timezone.utc) - RETENTION
    rows = db.execute(
        select(EventLog.map_id, EventLog.seq, EventLog.created_at)
        .where(EventLog.created_at >= cutoff)
        .distinct(EventLog.map_id)
        .order_by(EventLog.map_id, EventLog.seq.desc())
    ).all()
    return {map_id: (seq, created_at) for map_id, seq, created_at in rows}


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(#431) — 이 지도들의 이벤트 로그를 지운다. 테이블 이름 → 지운 행 수."""
    if not map_ids:
        return {"event_log": 0}
    return {"event_log": db.execute(delete(EventLog).where(EventLog.map_id.in_(map_ids))).rowcount}

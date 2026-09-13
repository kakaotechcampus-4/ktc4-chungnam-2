"""seq는 INSERT 시점에 배정되고 행은 COMMIT 시점에 보인다 — 동시 트랜잭션이 역순으로
커밋하면 폴러가 구멍을 건너뛰어 이벤트를 영구히 잃는다. 그래서 '연속된 앞부분'만 내보내고,
구멍은 GRACE 동안 기다린다. GRACE가 지나도 안 채워지면 롤백된 트랜잭션이 태운 번호로 보고
(abort된 트랜잭션도 시퀀스를 소비하므로 구멍은 정상이다) 건너뛴다."""

from datetime import datetime, timedelta

GRACE = timedelta(seconds=2)   # 우리 트랜잭션 중 가장 긴 것보다 넉넉히 길게


def advance(last_seen: int, rows: list, now: datetime, gap_since: dict[int, datetime]
            ) -> tuple[list, int, dict[int, datetime]]:
    """rows: last_seen보다 큰 seq를 가진, 지금 조회된 event_log 행들(정렬 여부 무관 — 여기서
    정렬한다). 반환: (내보낼 행 목록, 새 last_seen, 갱신된 gap_since)."""
    emit: list = []
    seq = last_seen
    for row in sorted(rows, key=lambda r: r.seq):
        if row.seq <= seq:
            continue   # 이미 처리된 행 재조회 방어
        if row.seq == seq + 1:
            emit.append(row)
            seq = row.seq
            gap_since.pop(seq, None)
            continue
        # row.seq > seq + 1: 구멍 발견. GRACE 안이면 기다린다.
        gap_seq = seq + 1
        first_seen = gap_since.setdefault(gap_seq, now)
        if now - first_seen < GRACE:
            break   # 아직 GRACE 안 지남 — 이번 tick은 여기서 멈춘다(이 row도 다음 tick에 재검토)
        # GRACE 지남 — 구멍을 건너뛰고 이 row를 그 자리에서 바로 낸다.
        gap_since.pop(gap_seq, None)
        emit.append(row)
        seq = row.seq
    return emit, seq, gap_since

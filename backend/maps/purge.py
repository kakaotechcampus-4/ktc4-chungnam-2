"""삭제한 지 오래된 지도와 딸린 데이터를 실제로 지우는 정리 명령(#431, docs/architecture.md 1.4절). 사용법:

    python -m maps.purge --older-than-days 30 [--dry-run]

- 대상은 `deleted_at`이 찍혔고 N일(기본 30)이 지난 지도뿐이다. 삭제 안 된 지도·기간이 안 된 지도·다른
  지도의 데이터에는 손대지 않는다. `places`·`place_facts`·`users`는 지도에 속하지 않아 지우지 않는다.
- 각 모듈이 자기 테이블만 지운다(`<module>.api.purge_map_data`). 여기서 자식 테이블부터 순서대로 부른다.
  FK가 연쇄 삭제가 아니고(NO ACTION) map_id에 FK가 없는 테이블도 있어서 순서가 곧 정확성이다.
- 한 트랜잭션이다. 하나라도 실패하면 전부 되돌린다. `--dry-run`은 같은 삭제를 실행한 뒤 롤백해서
  지울 행 수를 정확히 보여 주고 아무것도 남기지 않는다(places/load.py의 --dry-run과 같은 방식).
- 예약 실행은 없다. 배포 환경을 정할 때 붙인다(#168).
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from maps import api as maps_api
from maps.models import Map as MapRow
from pins import api as pins_api
from realtime import api as realtime_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api

DEFAULT_OLDER_THAN_DAYS = 30

# 자식 → 부모 순서. shortlist_items가 pins를, recommend 자식들이 recommend_runs를, reactions가 pins를,
# memberships·invites가 maps를 참조한다. event_log는 FK가 없지만 지도가 사라지기 전에 지운다.
PURGE_STEPS: tuple[Callable[..., dict[str, int]], ...] = (
    shortlist_api.purge_map_data,
    recommend_api.purge_map_data,
    pins_api.purge_map_data,
    realtime_api.purge_map_data,
    maps_api.purge_map_data,
)


def purge_cutoff(now: datetime, older_than_days: int) -> datetime:
    """이 시각 이전에 삭제된 지도가 대상이다."""
    return now - timedelta(days=older_than_days)


def format_report(map_count: int, counts: dict[str, int], *, dry_run: bool) -> str:
    lines = [f"[dry-run] 지울 지도 {map_count}개" if dry_run else f"지운 지도 {map_count}개"]
    lines += [f"  {table}: {count}" for table, count in counts.items()]
    lines.append(f"  합계: {sum(counts.values())}행")
    if dry_run:
        lines.append("(dry-run: 아무것도 지우지 않았다)")
    return "\n".join(lines)


def find_expired_map_ids(db: Session, *, now: datetime, older_than_days: int) -> list[str]:
    cutoff = purge_cutoff(now, older_than_days)
    return list(db.execute(
        select(MapRow.id).where(MapRow.deleted_at.is_not(None), MapRow.deleted_at <= cutoff).order_by(MapRow.id)
    ).scalars().all())


def purge(db: Session, *, now: datetime, older_than_days: int) -> tuple[int, dict[str, int]]:
    """대상 지도의 데이터를 순서대로 지우고 (지도 수, 테이블 → 지운 행 수)를 돌려준다. 커밋하지 않는다."""
    map_ids = find_expired_map_ids(db, now=now, older_than_days=older_than_days)
    counts: dict[str, int] = {}
    for step in PURGE_STEPS:
        counts.update(step(db, map_ids=map_ids))
    return len(map_ids), counts


def _days(raw: str) -> int:
    days = int(raw)
    if days < 1:
        raise argparse.ArgumentTypeError("1 이상이어야 한다(0일이면 방금 지운 지도까지 바로 파기된다)")
    return days


def main(argv: list[str] | None = None, *, session_factory=None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maps.purge", description="삭제한 지 오래된 지도와 딸린 데이터를 지운다.")
    parser.add_argument("--older-than-days", type=_days, default=DEFAULT_OLDER_THAN_DAYS,
                        help=f"삭제한 지 이만큼 지난 지도만(기본 {DEFAULT_OLDER_THAN_DAYS})")
    parser.add_argument("--dry-run", action="store_true", help="지울 지도 수와 테이블별 행 수만 보여 주고 지우지 않는다")
    args = parser.parse_args(argv)

    if session_factory is None:
        from common.database import SessionLocal

        session_factory = SessionLocal

    db = session_factory()
    try:
        map_count, counts = purge(
            db, now=now or datetime.now(timezone.utc), older_than_days=args.older_than_days
        )
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(format_report(map_count, counts, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())

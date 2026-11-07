"""삭제한 지 오래된 지도와 딸린 데이터를 실제로 지운다(#431, docs/architecture.md 1.4절). 정기 정리(`python -m maintenance.run
--only maps [--dry-run]`)가 `maps.api.purge_deleted_maps`로 부른다. 따로 돌리는 명령은 없다(#1474 — 정리 입구는 maintenance 하나).

- 대상은 `deleted_at`이 찍혔고 복구 기간(`core.TRASH_RETENTION`)이 지난 지도뿐이다. 경계는 `core.purge_cutoff` 한 곳이고
  복구 판정과 같다. 삭제 안 된 지도·기간이 안 된 지도·다른 지도의 데이터에는 손대지 않는다. `places`·`place_facts`·`users`는
  지도에 속하지 않아 지우지 않는다.
- 각 모듈이 자기 테이블만 지운다(`<module>.api.purge_map_data`). 여기서 자식 테이블부터 순서대로 부른다.
  FK가 연쇄 삭제가 아니고(NO ACTION) map_id에 FK가 없는 테이블도 있어서 순서가 곧 정확성이다.
- 커밋하지 않는다. 한 단계라도 실패하면 호출자(maintenance)가 그 트랜잭션을 통째로 되돌린다.
"""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent import api as agent_api
from maps import api as maps_api
from maps import core
from maps.models import Map as MapRow
from pins import api as pins_api
from realtime import api as realtime_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api

# 자식 → 부모 순서. shortlist_items가 pins를, recommend 자식들이 recommend_runs를, reactions가 pins를,
# memberships·invites가 maps를 참조한다. event_log는 FK가 없지만 지도가 사라지기 전에 지운다.
# agent_* 테이블은 다른 모듈 테이블을 참조하지 않고 참조받지도 않아 순서와 무관하다(#512) — 맨 앞에 둔다.
PURGE_STEPS: tuple[Callable[..., dict[str, int]], ...] = (
    agent_api.purge_map_data,
    agent_api.purge_course_runs,
    shortlist_api.purge_map_data,
    recommend_api.purge_map_data,
    pins_api.purge_map_data,
    realtime_api.purge_map_data,
    maps_api.purge_map_data,
)


def find_expired_map_ids(db: Session, *, now: datetime, lock: bool = False) -> list[str]:
    """lock=True면 대상 지도 행을 id 순으로 FOR UPDATE 잠근다 — 복구(maps.restore_map·restore_maps_deleted_by_withdrawal)가 같은 행을
    쥐고 있으면 끝나기를 기다렸다가 조건(deleted_at이 찍혀 있고 기한이 지났다)을 다시 본다. 방금 복구된 지도는 빠진다.
    잠그지 않으면 자식 데이터를 지운 뒤 마지막 지도 DELETE만 잠금을 기다려, 복구가 커밋된 지도의 행이 지워진다."""
    cutoff = core.purge_cutoff(now)
    stmt = select(MapRow.id).where(MapRow.deleted_at.is_not(None), MapRow.deleted_at <= cutoff).order_by(MapRow.id)
    if lock:
        stmt = stmt.with_for_update()
    return list(db.execute(stmt).scalars().all())


def purge(db: Session, *, now: datetime) -> tuple[int, dict[str, int]]:
    """대상 지도의 데이터를 순서대로 지우고 (지도 수, 테이블 → 지운 행 수)를 돌려준다. 커밋하지 않는다."""
    map_ids = find_expired_map_ids(db, now=now, lock=True)
    counts: dict[str, int] = {}
    for step in PURGE_STEPS:
        counts.update(step(db, map_ids=map_ids))
    return len(map_ids), counts

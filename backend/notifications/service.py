"""
얇은 I/O 셸 — 입력 수집 → core 호출 → DB 반영. 분기·계산은 notifications/core.py에 있다.
커밋하지 않는다 — common.database.session_scope가 요청당 한 번 커밋하는 유일한 지점이다(flush만 쓴다).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from common.errors import AppError
from notifications import core
from notifications.models import Notification as NotificationRow
from notifications.models import NotificationPref as PrefRow
from notifications.schemas import Notification, NotificationList, NotificationPref, NotificationPrefs

RETENTION_DAYS = 90


def notify(db: Session, *, user_id: str, type: str, map_id: str, map_title: str | None, message: str,
           pin_id: str | None = None, actor_id: str | None = None) -> uuid.UUID | None:
    """수신자 한 명에게 알림 한 행을 쓴다. 만들었으면 id, 거르면 None.

    거르는 규칙은 여기서만 판단한다 — 호출하는 쪽이 미리 걸러 둘 필요가 없다.
    - 행위자 본인: `actor_id`가 수신자와 같으면 만들지 않는다(내가 한 일의 알림은 나에게 없다).
    - 꺼 둔 종류: notification_prefs에 enabled=false 행이 있으면 만들지 않는다. 행이 없으면 켜짐.
    """
    if not core.is_known_type(type):
        raise ValueError(f"모르는 알림 종류: {type!r}")
    if actor_id is not None and actor_id == user_id:
        return None
    enabled = db.execute(
        select(PrefRow.enabled).where(PrefRow.user_id == user_id, PrefRow.type == type)
    ).scalar_one_or_none()
    if enabled is False:
        return None
    row = NotificationRow(
        user_id=user_id, type=type, map_id=map_id,
        map_title=core.clip(map_title, core.MAP_TITLE_MAX) if map_title else None,
        pin_id=pin_id, message=core.clip(message, core.MESSAGE_MAX),
    )
    db.add(row)
    db.flush()
    return row.id


def list_notifications(db: Session, *, user_id: str, limit: int, before: str | None,
                       unread_only: bool) -> NotificationList:
    query = select(NotificationRow).where(NotificationRow.user_id == user_id)
    if unread_only:
        query = query.where(NotificationRow.read_at.is_(None))
    if before is not None:
        try:
            cursor_at, cursor_id = core.decode_cursor(before)
        except ValueError as exc:
            raise AppError("VALIDATION_ERROR", "before 값이 올바르지 않습니다") from exc
        query = query.where(tuple_(NotificationRow.created_at, NotificationRow.id) < tuple_(cursor_at, cursor_id))
    rows = db.execute(
        query.order_by(NotificationRow.created_at.desc(), NotificationRow.id.desc()).limit(limit + 1)
    ).scalars().all()
    page = rows[:limit]
    next_before = core.encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return NotificationList(
        items=[_to_schema(row) for row in page],
        unread_count=unread_count(db, user_id=user_id),
        next_before=next_before,
    )


def unread_count(db: Session, *, user_id: str) -> int:
    """페이지·필터와 무관한 전체 안 읽은 수."""
    return db.execute(
        select(func.count()).select_from(NotificationRow)
        .where(NotificationRow.user_id == user_id, NotificationRow.read_at.is_(None))
    ).scalar_one()


def mark_read(db: Session, *, user_id: str, ids: list[str] | None) -> int:
    """읽음 처리 — 멱등이다. 내 알림 중 아직 안 읽은 것만 바꾸고, 남의 id·없는 id·형식이 틀린 id는 무시한다.
    `ids=None`이면 내 알림 전부. 바뀐 행 수를 돌려준다."""
    stmt = (
        update(NotificationRow)
        .where(NotificationRow.user_id == user_id, NotificationRow.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    if ids is not None:
        stmt = stmt.where(NotificationRow.id.in_(core.parse_ids(ids)))
    return db.execute(stmt).rowcount


def get_prefs(db: Session, *, user_id: str) -> NotificationPrefs:
    stored = dict(db.execute(select(PrefRow.type, PrefRow.enabled).where(PrefRow.user_id == user_id)).all())
    return NotificationPrefs(prefs=[NotificationPref(type=t, enabled=e) for t, e in core.effective_prefs(stored)])


def update_prefs(db: Session, *, user_id: str, updates: list[tuple[str, bool]]) -> NotificationPrefs:
    """보낸 종류만 바꾼다(없던 행은 만든다). 이미 쌓인 알림은 건드리지 않는다."""
    for type, enabled in core.last_wins(updates).items():
        if not core.is_known_type(type):
            raise ValueError(f"모르는 알림 종류: {type!r}")
        db.execute(
            pg_insert(PrefRow).values(user_id=user_id, type=type, enabled=enabled)
            .on_conflict_do_update(index_elements=[PrefRow.user_id, PrefRow.type], set_={"enabled": enabled})
        )
    db.flush()
    return get_prefs(db, user_id=user_id)


def delete_by_user(db: Session, *, user_id: str) -> dict[str, int]:
    """탈퇴(#155) — 그 사람의 알림함과 설정을 모두 지운다. 테이블 이름 → 지운 행 수."""
    return {
        "notifications": db.execute(delete(NotificationRow).where(NotificationRow.user_id == user_id)).rowcount,
        "notification_prefs": db.execute(delete(PrefRow).where(PrefRow.user_id == user_id)).rowcount,
    }


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#560) — from_user의 알림함을 to_user로 옮긴다. 테이블 이름 → 옮긴 행 수.
    알림은 읽음 상태·created_at·문장 그대로 user_id만 바꾼다. 알림 설정은 to_user의 기존 값이 이긴다:
    같은 종류가 양쪽에 있으면 게스트 것을 지우고, 게스트에만 있는 종류는 to_user에 그 종류 행이 없을 때만 옮긴다.
    멱등이고 같은 id면 아무것도 하지 않는다."""
    if from_user_id == to_user_id:
        return {"notifications": 0, "notification_prefs": 0}
    moved = db.execute(
        update(NotificationRow).where(NotificationRow.user_id == from_user_id).values(user_id=to_user_id)
    ).rowcount
    kept_types = select(PrefRow.type).where(PrefRow.user_id == to_user_id)
    db.execute(delete(PrefRow).where(PrefRow.user_id == from_user_id, PrefRow.type.in_(kept_types)))
    prefs_moved = db.execute(
        update(PrefRow).where(PrefRow.user_id == from_user_id).values(user_id=to_user_id)
    ).rowcount
    return {"notifications": moved, "notification_prefs": prefs_moved}


def purge_old(db: Session, *, now: datetime, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    """`now` 기준 N일(기본 90)이 지난 알림을 지운다. 읽었든 안 읽었든 같다. 설정은 건드리지 않는다."""
    cutoff = now - timedelta(days=older_than_days)
    return {"notifications": db.execute(delete(NotificationRow).where(NotificationRow.created_at < cutoff)).rowcount}


def _to_schema(row: NotificationRow) -> Notification:
    return Notification(
        id=str(row.id), type=row.type, map_id=row.map_id, map_title=row.map_title, pin_id=row.pin_id,
        message=row.message, created_at=row.created_at, read=row.read_at is not None,
    )

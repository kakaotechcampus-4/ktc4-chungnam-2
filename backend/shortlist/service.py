"""
얇은 I/O 셸 — shortlist_items 테이블 CRUD만 한다(docs/code-quality.md). 분기·조립 로직은
shortlist/core.py로, pins 테이블을 건드리는 부분은 shortlist/flows.py(pins.api 경유)로 위임한다.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError
from shortlist.models import ShortlistItem as ShortlistItemRow


def _find_existing_item(db: Session, map_id: str, pin_id: str) -> ShortlistItemRow:
    return db.execute(
        select(ShortlistItemRow).where(
            ShortlistItemRow.map_id == map_id, ShortlistItemRow.pin_id == uuid.UUID(pin_id),
        )
    ).scalar_one()


def add_item(db: Session, *, map_id: str, pin_id: str, added_by: str) -> tuple[ShortlistItemRow, bool]:
    """unique(map_id, pin_id) 위반을 세이브포인트로 잡아 이미 있던 행을 돌려준다
    (pins.api.create_ai_pin과 같은 패턴 — db.rollback()을 begin_nested()와 함께 반드시 부른다,
    안 그러면 세션이 PendingRollbackError로 죽는다). 반환한 bool이 flows.confirm_pin의 멱등
    분기 기준이다 — False면 pins.kind 재변경도 이벤트도 건너뛴다."""
    row = ShortlistItemRow(map_id=map_id, pin_id=uuid.UUID(pin_id), added_by=added_by)
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        sqlstate = getattr(exc.orig, "pgcode", None)
        if sqlstate == "23505" and "uq_shortlist_map_pin" in str(exc.orig):
            return _find_existing_item(db, map_id, pin_id), False
        raise
    return row, True


def get_item_or_404(db: Session, item_id: str) -> ShortlistItemRow:
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    row = db.execute(select(ShortlistItemRow).where(ShortlistItemRow.id == item_uuid)).scalar_one_or_none()
    if row is None:
        raise AppError("NOT_FOUND")
    return row


def delete_item(db: Session, item_id: str) -> None:
    """core delete() 구문을 쓴다(pins/service.py::delete_reaction과 같은 이유) — ORM
    session.delete(row)와 달리 이미 읽어둔 row 인스턴스를 만료시키지 않는다."""
    db.execute(delete(ShortlistItemRow).where(ShortlistItemRow.id == uuid.UUID(item_id)))
    db.flush()


def list_items(db: Session, *, map_id: str) -> list[ShortlistItemRow]:
    return list(
        db.execute(
            select(ShortlistItemRow)
            .where(ShortlistItemRow.map_id == map_id)
            .order_by(ShortlistItemRow.added_at)
        ).scalars()
    )

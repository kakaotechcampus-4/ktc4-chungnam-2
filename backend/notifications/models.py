"""
notifications 모듈이 소유하는 테이블 2개 — docs/data-model.md notifications 절이 정본이다(마이그레이션 0031).

- `map_id`·`pin_id`에는 FK를 걸지 않는다. 지도가 삭제돼도(`map_deleted` 알림) 핀이 지워져도 알림은 남는다.
- `type`은 text다. 종류는 앞으로 늘어난다(지도 복구 #464, 강퇴 #8) — 허용 값은 core.TYPES가 정하고 쓰는 쪽이 지킨다.
- `message`에는 반대 사유 원문·핀 메모를 넣지 않는다. 서버가 만든 문장만 담는다.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text, desc, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


def _now() -> datetime:
    # server_default(now())는 한 트랜잭션 안의 행이 모두 같은 시각이라 최근순 정렬이 흔들린다 — 파이썬 시계를 쓴다
    return datetime.now(timezone.utc)


class Notification(Base):
    """사용자별 알림함. 수신자마다 한 행. 90일이 지나면 정리 작업(#168)이 지운다."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", desc("created_at")),
        Index("ix_notifications_user_unread", "user_id", postgresql_where=text("read_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    map_title: Mapped[str | None] = mapped_column(String, nullable=True)
    pin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationPref(Base):
    """알림 종류별 켜고 끄기. 행이 없으면 켜짐(기본값)."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)

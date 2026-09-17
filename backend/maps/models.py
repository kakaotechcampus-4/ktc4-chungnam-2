"""
maps / memberships / invites (docs/data-model.md).

maps.id는 UUID가 아니라 String이다 — pins.map_id·shortlist_items.map_id가 이미 String으로
"maps 도착 시 FK 추가"라는 주석과 함께 유보돼 있다(0001_pins.py, 0004_shortlist_items.py).
String이면 그 FK 추가가 순수 제약 추가로 끝나지만, UUID였다면 다른 두 모듈 테이블의 컬럼
타입을 바꿔야 하고(ALTER COLUMN ... TYPE uuid USING) 기존 dev 행("map_1" 등)에서 실패한다 —
maps가 단독으로 결정할 수 없는 변경이라 String을 유지한다.

memberships.id는 반대로 UUID다 — 이 값은 모듈 경계를 넘어 다니지 않는다(비대칭은 의도적).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

MembershipRole = Enum("member", "owner", name="membership_role")


def _new_map_id() -> str:
    return str(uuid.uuid4())


class Map(Base):
    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_map_id)
    title: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date] = mapped_column(nullable=False)
    # API 대응 필드가 없다 — MapCreateRequest에도 Map 응답에도 없다. data-model.md가 선언한
    # 컬럼이라 스키마는 맞추되 이 모듈은 절대 쓰지 않는다(항상 NULL). #32 확정 전까지 보류
    # (maps/for_Root.md 참고).
    member_count_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — auth 도착 시 FK
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("end_date >= start_date", name="ck_maps_date_order"),)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, ForeignKey("maps.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — auth 도착 시 FK
    role: Mapped[str] = mapped_column(MembershipRole, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("map_id", "user_id", name="uq_memberships_map_user"),)


class Invite(Base):
    __tablename__ = "invites"

    # data-model.md에 별도 id가 없다 — token 자체가 PK다.
    token: Mapped[str] = mapped_column(String, primary_key=True)
    map_id: Mapped[str] = mapped_column(String, ForeignKey("maps.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — auth 도착 시 FK
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

"""
maps / memberships / invites (docs/data-model.md).

maps.id는 UUID가 아니라 String이다 — 다른 모듈의 map_id 열(pins, shortlist_items 등)이 String이다.
다른 모듈 테이블을 가리키는 열에는 FK를 걸지 않는다(docs/architecture.md 1절, #760).

memberships.id는 반대로 UUID다 — 이 값은 모듈 경계를 넘어 다니지 않는다(비대칭은 의도적).
"""

import uuid
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
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
    # 지역 검색(선택) — 9/28 #22 변경(PR #132, 루트 검증 후 승인). 둘 다 NULL이거나 둘 다
    # 값이 있어야 한다(아래 CHECK). 없으면 지금처럼 첫 핀 좌표로 지역을 정한다.
    region_label: Mapped[str | None] = mapped_column(String, nullable=True)
    region_center = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — 모듈 경계라 FK 없음(#760)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 방장이 지도를 삭제하면 찍는다(soft delete, #369). 찍힌 지도는 get_map_or_404·
    # DbMembershipGateway·list_maps·초대 조회가 모두 없는 지도로 답한다. 실제 파기는 범위 밖.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_maps_date_order"),
        CheckConstraint(
            "(region_label IS NULL) = (region_center IS NULL)",
            name="ck_maps_region_both_or_neither",
        ),
    )


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, ForeignKey("maps.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — 모듈 경계라 FK 없음(#760)
    role: Mapped[str] = mapped_column(MembershipRole, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("map_id", "user_id", name="uq_memberships_map_user"),
        # (map_id, user_id) 복합 유니크 인덱스는 선두 컬럼이 map_id라 `WHERE user_id = X`
        # 단독 조회(maps/service.py::list_maps)를 못 탄다 — #137, Antigravity 검수로 발견.
        # map_id 단독 조회(_member_count·list_members)는 그 복합 인덱스로 이미 충분해 건드리지
        # 않는다.
        Index("ix_memberships_user_id", "user_id"),
        # 지도당 방장은 최대 1명(#369). 방장 판단의 정본은 role이다(maps.created_by가 아니다).
        # 위임은 한 트랜잭션에서 강등을 먼저, 승격을 나중에 한다 — 이 인덱스는 문장마다 검사된다.
        Index(
            "uq_memberships_one_owner_per_map", "map_id",
            unique=True, postgresql_where=text("role = 'owner'"),
        ),
    )


class Invite(Base):
    __tablename__ = "invites"

    # data-model.md에 별도 id가 없다 — token 자체가 PK다.
    token: Mapped[str] = mapped_column(String, primary_key=True)
    map_id: Mapped[str] = mapped_column(String, ForeignKey("maps.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # users(id) — 모듈 경계라 FK 없음(#760)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 방장이 링크를 끈 시각(#467). 켜져 있으면 NULL. 끈 링크는 요약·수락이 410 INVITE_REVOKED다.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_invites_map_id", "map_id"),)  # 지도별 목록·내 링크 재사용 조회

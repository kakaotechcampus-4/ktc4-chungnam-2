"""
이 모듈이 소유하는 테이블만 정의한다(docs/data-model.md 37-60행, backend/CLAUDE.md).
reactions 테이블은 엔드포인트(#17)가 아직 없어도 여기서 함께 정의한다 — Pin.reaction_summary를
빈 집계가 아니라 실제 데이터로 계산하려면 테이블이 있어야 한다.
"""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

Category = Enum(
    "음식점", "카페", "숙소", "관광지",
    name="category",
)
PinKind = Enum(
    "일반", "AI추천", "확정",
    name="pin_kind",
)
PinOrigin = Enum(
    "direct", "ai",
    name="pin_origin",
)
Visibility = Enum(
    "public", "private",
    name="visibility",
)
ReactionType = Enum(
    "like", "neutral", "against",
    name="reaction_type",
)


class Pin(Base):
    __tablename__ = "pins"

    # id는 이 모듈이 전적으로 소유하므로 UUID로 발급한다.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # map_id/created_by/place_id: auth·maps·places가 아직 없어 ID 형식(UUID vs 문자열)이 정해지지
    # 않았다. 그 모듈들이 오기 전까지는 String으로 받아 형식을 강제하지 않는다 — FK도 그때 건다(루트 보고 대상).
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(Category, nullable=False)
    kind: Mapped[str] = mapped_column(PinKind, nullable=False)
    origin: Mapped[str] = mapped_column(PinOrigin, nullable=False)
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    visibility: Mapped[str] = mapped_column(Visibility, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 가드레일 6 / 중복 판정(#33 보류) — data-model.md의 unique(map_id, place_id) where deleted_at is null 그대로.
        Index(
            "uq_pins_map_place",
            "map_id",
            "place_id",
            unique=True,
            postgresql_where=deleted_at.is_(None),
        ),
    )


class Reaction(Base):
    __tablename__ = "reactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pins.id"), nullable=False)
    # users(id) 대상 테이블이 아직 없다 — FK는 걸지 않는다. map_id와 같은 이유로 String.
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(ReactionType, nullable=False)
    reason_text: Mapped[str | None] = mapped_column(String, nullable=True)
    reason_chip_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("pin_id", "user_id", name="uq_reactions_pin_user"),
    )

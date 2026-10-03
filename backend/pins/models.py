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

from common import categories
from common.database import Base

Category = Enum(*categories.all_categories(), name="category")  # 값은 common/categories.py(#280)
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
    # #195: places.id(자체 DB 장소)의 문자열. 이름은 places.name에서 읽는다(핀에 저장하지 않는다 —
    # 카카오 응답의 이름·좌표는 저장 금지, #53). DB FK·UUID 타입은 걸지 않았다 — for_Root.md 참고.
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    # 매칭된 places.geom의 복사(자체 데이터). 사용자가 보낸 좌표는 저장하지 않는다.
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    # #57 결정: candidate.checks를 게시 시점에 복사(가드레일 5) — recommend를 다시 조회하지
    # 않는다. reason_chip_ids와 같은 방식(JSONB, 목록형이라 nullable).
    checks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # #157: checks와 같은 방식으로 게시 시점에 candidate 값을 복사한다(가드레일 5). recommend가
    # candidate에 값을 채우기 전에는 항상 NULL — 통로만 있다.
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    member_fulfillment: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    place_source: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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

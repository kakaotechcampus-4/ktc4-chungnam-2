"""
이 모듈이 소유하는 테이블만 정의한다(docs/data-model.md 58-62행, backend/CLAUDE.md).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


class ShortlistItem(Base):
    __tablename__ = "shortlist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # map_id: auth/maps가 아직 없어 pins.models와 같은 이유로 String(FK 없음, 루트 보고 대상).
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    pin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pins.id"), nullable=False)
    added_by: Mapped[str] = mapped_column(String, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # #30 수동 정렬(9/4 결정, 허용 확정) 전용 컬럼 — docs/data-model.md 80-84행: 동선(routes
    # 테이블, #103)과는 무관한 별개 값이다. routes 재계산은 이 컬럼을 읽지도 쓰지도 않는다.
    # 수동 정렬(PUT .../shortlist/order) 자체는 별도 이슈라 이번 커밋도 값을 쓰지 않는다.
    visit_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("map_id", "pin_id", name="uq_shortlist_map_pin"),
    )


class Route(Base):
    """5-10 동선 계산 결과 — docs/data-model.md 88-109행(#103 대응으로 루트가 이미 정의).
    POST /maps/{mapId}/route가 부를 때마다 해당 map_id의 기존 행을 지우고 새로 쓴다. 여러
    지역에 걸치면 지역 하나당 행 하나(region_label). `ordered_pin_ids`·`legs`는 API 응답 모양을
    그대로 jsonb로 저장한다 — candidates.checks와 같은 패턴. `unique(map_id, region_label)`은
    data-model.md 96행 주석대로 동시 POST 재계산이 같은 지역 행을 중복 적재하는 걸 막는
    방어용이다(경합 시 조용한 중복 대신 IntegrityError로 드러난다)."""

    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    region_label: Mapped[str] = mapped_column(String, nullable=False)
    ordered_pin_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    total_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    legs: Mapped[list] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("map_id", "region_label", name="uq_routes_map_region"),
        Index("ix_routes_map_id", "map_id"),
    )

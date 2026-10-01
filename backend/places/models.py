"""
이 모듈이 소유하는 테이블만 정의한다(docs/data-model.md "places / place_facts", backend/CLAUDE.md).

places는 자체 장소 DB다(#53). 이름·좌표·주소는 인허가 공공데이터와 TourAPI에서만 온다 — 카카오 응답은
저장하지 않는다. 카카오 장소 ID·URL·확인 일자(kakao_*)만 예외(저장 허용 범위).
"""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

# pins.category enum("category")는 5값이라 따로 둔다 — 자체 DB는 음식점·카페·관광지만 담는다(숙소·기타 없음).
PlaceCategory = Enum("음식점", "카페", "관광지", name="place_category")
PlaceSourceEnum = Enum("permit", "tourapi", name="place_source")
PlaceStatus = Enum("open", "closed", name="place_status")
FactConfidence = Enum("known", "unknown", name="fact_confidence")


class Place(Base):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(PlaceSourceEnum, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)   # 그 데이터셋의 관리번호/콘텐츠 ID
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(PlaceCategory, nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    # 좌표계가 위경도가 아니면 적재 시 변환해 넣는다. 좌표 없는 행은 적재하지 않으므로 NOT NULL.
    # GiST 인덱스는 geoalchemy2가 spatial_index(기본 True)로 만든다 — idx_places_geom.
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    status: Mapped[str] = mapped_column(PlaceStatus, nullable=False, server_default="open")
    # 사용자가 검색해서 고를 때 한 건씩 매칭한 결과. 카카오 응답의 이름·주소·좌표는 저장하지 않는다.
    kakao_place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kakao_place_url: Mapped[str | None] = mapped_column(String, nullable=True)
    kakao_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_places_source_source_id"),)


class PlaceFact(Base):
    """place_facts는 캐시가 아니다 — TTL로 만료시키지 않는다. 다시 라벨링하면 덮어쓴다(labeled_at 갱신)."""

    __tablename__ = "place_facts"

    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    fact_key: Mapped[str] = mapped_column(String, primary_key=True)
    value = mapped_column(JSONB(none_as_null=True), nullable=True)   # boolean/enum. confidence=unknown이면 NULL
    confidence: Mapped[str] = mapped_column(FactConfidence, nullable=False)
    source_layer: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # architecture.md 3층 모델
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)  # v2 모델 라벨링부터
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("source_layer IN (1, 2, 3)", name="ck_place_facts_source_layer"),)

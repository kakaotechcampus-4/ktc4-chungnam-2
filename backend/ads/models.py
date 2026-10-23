"""
ads 모듈이 소유하는 테이블 2개 — docs/data-model.md ads 절과 docs/ads.md 6절이 정본이다(마이그레이션 0036).

- `ads.place_id`는 places.id지만 모듈 경계라 FK를 걸지 않는다(agent, pins.source_run_id와 같은 관례). 존재와 status=open은
  등록 스크립트가 places.api로 검증하고, 장소가 정리되면 선택 규칙(places.api.get_ad_places 결과에 없음)으로 자연히 빠진다.
- 카테고리는 저장하지 않는다. places.category에서 읽는다(같은 값을 두 곳에 두지 않는다).
- `ad_daily_stats`는 광고별 날짜별 수만 남긴다. user_id, map_id 칸을 두지 않는다(명세 2절 7번).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


class Ad(Base):
    """기간을 정해 추천 탭 하단에 노출하는 places 행 하나."""

    __tablename__ = "ads"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_ads_period"),
        Index("uq_ads_place_active", "place_id", unique=True, postgresql_where=text("active")),   # 같은 장소에 active는 하나
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   # 이 시각은 포함하지 않는다
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    memo: Mapped[str | None] = mapped_column(String, nullable=True)   # 광고주, 계약 메모 — 응답에 내보내지 않는다
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AdDailyStat(Base):
    """광고별 날짜별(AD_STATS_TZ) 노출·클릭 수. 증가는 INSERT ... ON CONFLICT (ad_id, stat_date) DO UPDATE로만 한다."""

    __tablename__ = "ad_daily_stats"

    ad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ads.id"), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    served_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")   # 응답에 실린 횟수
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

"""
이 모듈이 소유하는 테이블만 정의한다(docs/data-model.md 58-62행, backend/CLAUDE.md).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
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
    # 5-10 자동계산 결과 + #30 수동 정렬(9/4 결정, 허용 확정, docs/data-model.md) 둘 다 이 컬럼을
    # 쓴다. 이번 커밋은 값을 쓰지 않는다 — 동선 계산·수동 정렬은 별도 착수(shortlist/CLAUDE.md
    # "넘지 말 것": 지역 클러스터링 공통 유틸을 recommend와 어떻게 나눌지 루트 확인 필요, for_Root.md 참고).
    visit_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("map_id", "pin_id", name="uq_shortlist_map_pin"),
    )

"""
reviews 모듈이 소유하는 테이블 2개 — docs/data-model.md reviews 절과 docs/credits-reviews.md 6절이 정본이다(마이그레이션 0049).

- 후기는 핀이 아니라 자체 DB 장소(`places.id`)에 붙는다. 같은 장소의 후기는 어느 지도의 핀에서 봐도 같다.
- `place_id`와 사용자 id 열에 FK를 걸지 않는다(모듈 경계, #760, `ads.place_id` 선례).
- 숨김(`hidden_at`)은 관리 스크립트(reviews/scripts/hide.py)로만 바꾼다.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base
from reviews.constants import RATING_MAX, RATING_MIN, REVIEW_BODY_MAX


class Review(Base):
    """장소 후기 한 건 — 한 사람이 한 장소에 하나. 글은 앞뒤 공백을 걷은 뒤 저장한다."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("place_id", "user_id", name="uq_reviews_place_user"),
        CheckConstraint(f"rating BETWEEN {RATING_MIN} AND {RATING_MAX}", name="ck_reviews_rating"),
        CheckConstraint(f"char_length(body) BETWEEN 1 AND {REVIEW_BODY_MAX}", name="ck_reviews_body_length"),
        # 목록(최신순 커서)과 평균·개수는 숨기지 않은 후기만 읽는다
        Index("ix_reviews_place_created", "place_id", text("created_at DESC"), text("id DESC"),
              postgresql_where=text("hidden_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewReport(Base):
    """후기 신고 — 후기마다 한 사람 한 번(PK가 멱등을 맡는다). 후기를 지우면 같이 지워진다."""

    __tablename__ = "review_reports"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True,
    )
    reporter_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

"""feedback 모듈이 소유하는 테이블 — docs/data-model.md notifications / feedback 절이 정본이다(마이그레이션 0031).

`user_id`는 FK 없이 문자열이고 탈퇴하면 NULL로 끊는다(내용은 남긴다). `map_id`도 FK가 없고 검사 없이 저장한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

CATEGORIES = ("bug", "idea", "other")


def _new_id() -> str:
    return str(uuid.uuid4())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    map_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

"""
users (docs/data-model.md 10-16행). auth가 전적으로 소유하는 유일한 테이블 — memberships는
maps 소유(auth/CLAUDE.md "책임" 참고).

id는 다른 모듈들이 이미 String으로 참조를 걸어둔 형식과 맞춘다(maps.models::Map.created_by,
pins.models::Pin.created_by 등 — 전부 "users(id) — auth 도착 시 FK" 주석과 함께 String으로
유보돼 있었다). FK 추가는 이번 리비전 범위 밖이다(auth/for_Root.md 보고 대상 — 각 모듈이
이미 들고 있는 dev 값이 실제 users.id와 일치한다는 보장이 없어, 백필 없이 FK를 걸면 그
모듈들이 먼저 깨진다).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


def _new_user_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_user_id)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # 'kakao'뿐이지만 값 제약은 서비스 계층에서
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 탈퇴 시 soft delete(12절) — 하드 삭제하지 않는다. 다른 모듈이 이미 참조 중인 user_id가
    # 갑자기 사라지면(예: pins.created_by) 그쪽에서 예상 못한 404/조인 실패가 난다.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_users_provider_identity"),
    )

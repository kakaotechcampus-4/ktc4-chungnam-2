"""
users, user_identities (docs/data-model.md auth 절). auth가 전적으로 소유하는 테이블 — memberships는
maps 소유(auth/CLAUDE.md "책임" 참고).

users는 사람이고 user_identities는 로그인 수단이다(#694). 다른 모듈은 users.id만 가리킨다.
게스트 = 로그인 수단이 없는 사용자이고, is_guest는 저장하지 않고 users를 읽을 때 계산한다.

id는 다른 모듈들이 String으로 들고 있는 형식과 맞춘다(maps.models::Map.created_by,
pins.models::Pin.created_by 등). 다른 모듈의 이 열들에는 FK를 걸지 않는다(docs/architecture.md 1절, #760).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, exists, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column

from common.database import Base

IDENTITY_CONSTRAINT = "uq_user_identities_provider_identity"


def _new_user_id() -> str:
    return str(uuid.uuid4())


class UserIdentity(Base):
    """로그인 수단(#694). 카카오 계정 하나는 사람 하나에만, 한 사람에 카카오는 하나.
    탈퇴해도 지우지 않는다 — 같은 카카오 계정의 재로그인을 "탈퇴한 계정"으로 막는 근거다(#409)."""

    __tablename__ = "user_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # users는 탈퇴해도 soft delete라 CASCADE는 서비스에서 일어나지 않는다. 테스트 정리처럼 users 행을 실제로 지울 때만 따라 지운다
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # 'kakao'뿐이지만 값 제약은 서비스 계층에서
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name=IDENTITY_CONSTRAINT),
        UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_user_id)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 탈퇴 시 soft delete(12절) — 하드 삭제하지 않는다. 다른 모듈이 이미 참조 중인 user_id가
    # 갑자기 사라지면(예: pins.created_by) 그쪽에서 예상 못한 404/조인 실패가 난다.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 로그아웃 시각 — 이 시각 이전에 발급된 세션 토큰은 무효(무상태 토큰을 서버에서 폐기하는 유일한 수단).
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 게스트(이름만 입력한 임시 계정, #472). 토큰 하나당 10명 상한을 guest_invite_token으로 센다. 카카오 수단을 붙이면 비운다.
    guest_invite_token: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 게스트 = 로그인 수단이 없는 사용자(#694). 저장하면 수단을 붙일 때 함께 고치는 것을 빠뜨릴 수 있어 users를 읽는
    # SELECT에서 같이 계산한다. 행을 잠근 뒤의 판정에는 쓰지 않는다 — 잠금을 기다린 SELECT의 하위 질의는 잠금 전 스냅숏을 본다.
    is_guest: Mapped[bool] = column_property(
        ~exists().where(UserIdentity.user_id == id).correlate_except(UserIdentity)
    )

"""
credits 모듈이 소유하는 테이블 2개 — docs/data-model.md credits 절과 docs/credits-reviews.md 6절이 정본이다(마이그레이션 0048).

- 원본은 원장(`credit_ledger`)이다. `credit_accounts.balance`는 원장 합을 담아 두는 값으로, 행 잠금과 `CHECK (balance >= 0)`을
  걸 자리라서 둔다. 둘을 같은 트랜잭션에서 함께 바꾸는 곳은 service.py의 `_apply` 하나다.
- 사용자 id 열에 FK를 걸지 않는다(모듈 경계, #760).
- `ref_id` UNIQUE가 멱등을 맡는다(이중 차감, 이중 환불, 같은 장소 후기 보상 두 번).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


class CreditAccount(Base):
    """사람마다 하나인 잔액. 처음 쓰기(차감, 후기 보상) 때 만든다. 행이 없으면 읽기는 INITIAL_CREDITS로 본다."""

    __tablename__ = "credit_accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_credit_accounts_balance"),)

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CreditLedger(Base):
    """잔액이 바뀐 이유 한 줄. reason: initial | spend | refund | review."""

    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_user_reason_created", "user_id", "reason", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    ref_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

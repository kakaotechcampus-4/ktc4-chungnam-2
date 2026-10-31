"""크레딧과 계정 수명 — docs/credits-reviews.md 12절 7(#948 검수).

탈퇴 때는 남기고, 7일 안에 되살리면 잔액이 그대로이며, 7일 정리(auth.service.purge_withdrawn_user)와 「새 계정으로 시작」
(restart_account)에서 지운다. 실제 auth.service를 태운다 — 탈퇴는 모든 모듈의 WITHDRAW_STEPS를 돈다.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import main  # noqa: F401 — 탈퇴 단계가 모든 모듈 테이블을 건드린다(Base.metadata에 모두 등록)
from auth import core as auth_core
from auth import service as auth_service
from auth.testing import create_kakao_user
from credits import api
from credits.constants import INITIAL_CREDITS, PRICES
from credits.models import CreditAccount, CreditLedger

FEATURE = "recommend_run"


def _rows(db, user_id) -> tuple[int, int]:
    """(계정 행 수, 원장 행 수)."""
    accounts = db.execute(select(CreditAccount).where(CreditAccount.user_id == user_id)).all()
    ledger = db.execute(select(CreditLedger).where(CreditLedger.user_id == user_id)).all()
    return len(accounts), len(ledger)


@pytest.fixture()
def spent(db_session):
    """카카오 사용자 하나가 한 번 쓴 뒤 탈퇴했다. 탈퇴 시각은 하루 전으로 옮긴다(되살리기가 다음 초를 기다리지 않게)."""
    user = create_kakao_user(db_session, "credits_w1")
    balance = api.charge(db_session, user_id=user.id, feature=FEATURE, run_id=str(uuid.uuid4()))
    auth_service.withdraw_user(db_session, user_id=user.id)
    earlier = datetime.now(timezone.utc) - timedelta(days=1)
    user.deleted_at = earlier
    user.sessions_valid_after = earlier
    db_session.flush()
    return user.id, balance, auth_core.PendingClaims(user.id, "kakao", auth_core.deleted_at_stamp(earlier))


def test_withdraw_keeps_account_and_ledger(db_session, spent):
    user_id, balance, _ = spent

    assert _rows(db_session, user_id) == (1, 2)   # initial, spend
    assert api.get_balance(db_session, user_id=user_id) == balance


def test_restore_keeps_the_balance(db_session, spent):
    """되살리면 쓰던 잔액이 그대로다 — 처음 지급량으로 다시 시작하지 않는다."""
    user_id, balance, claims = spent

    auth_service.restore_account(db_session, claims=claims)

    assert api.get_balance(db_session, user_id=user_id) == balance == INITIAL_CREDITS - PRICES[FEATURE]
    api.charge(db_session, user_id=user_id, feature=FEATURE, run_id=str(uuid.uuid4()))
    reasons = db_session.execute(select(CreditLedger.reason).where(CreditLedger.user_id == user_id)).scalars().all()
    assert reasons.count("initial") == 1


def test_seven_day_purge_deletes_account_and_ledger(db_session, spent):
    user_id, _, _ = spent

    auth_service.purge_withdrawn_user(db_session, user_id=user_id)

    assert _rows(db_session, user_id) == (0, 0)


def test_purge_does_not_touch_a_live_account(db_session):
    """purge_withdrawn_user는 살아 있는 계정을 건드리지 않는다 — 크레딧도 그대로다."""
    user = create_kakao_user(db_session, "credits_live")
    api.charge(db_session, user_id=user.id, feature=FEATURE, run_id=str(uuid.uuid4()))

    auth_service.purge_withdrawn_user(db_session, user_id=user.id)

    assert _rows(db_session, user.id) == (1, 2)


def test_restart_deletes_old_rows_and_new_account_starts_at_initial(db_session, spent):
    user_id, _, claims = spent

    new = auth_service.restart_account(db_session, claims=claims)

    assert _rows(db_session, user_id) == (0, 0)
    assert new.id != user_id
    assert api.get_balance(db_session, user_id=new.id) == INITIAL_CREDITS

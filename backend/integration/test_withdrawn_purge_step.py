"""정기 정리의 `withdrawn` 단계(#857 3/3) — 러너가 auth 공개 함수를 불러 복구 기간이 지난 탈퇴 계정의 개인정보를 지운다."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from auth import core
from auth.models import User, UserIdentity
from auth.testing import create_kakao_user
from maintenance import run


def test_withdrawn_step_wipes_accounts_past_the_period_and_reports_the_count(db_session):
    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="k1", display_name="영희", deleted_at=now - timedelta(days=8))
    create_kakao_user(db_session, "inside", provider_user_id="k2", display_name="민수", deleted_at=now - timedelta(days=2))

    counts = run.STEPS["withdrawn"](db_session, now)

    assert counts == {"withdrawn_accounts": 1}
    assert db_session.get(User, "past").display_name == core.WITHDRAWN_DISPLAY_NAME
    assert db_session.execute(select(UserIdentity).where(UserIdentity.user_id == "past")).first() is None
    assert db_session.get(User, "inside").display_name == "민수"


def test_withdrawn_step_is_idempotent(db_session):
    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="k1", deleted_at=now - timedelta(days=8))

    assert run.STEPS["withdrawn"](db_session, now) == {"withdrawn_accounts": 1}
    assert run.STEPS["withdrawn"](db_session, now) == {"withdrawn_accounts": 0}

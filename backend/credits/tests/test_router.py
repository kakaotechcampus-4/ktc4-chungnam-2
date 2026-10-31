"""GET /credits/me — main.app을 그대로 태운다(docs/credits-reviews.md 12절 1, 4). 인증은 서명된 세션 쿠키."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from auth.testing import create_guest, ensure_users, session_cookie
from credits import api
from credits.constants import INITIAL_CREDITS, PRICES, REVIEW_REWARD
from credits.models import CreditAccount


def _client(app_client, user_id):
    return TestClient(app_client.app, cookies=session_cookie(user_id))


def test_requires_login(app_client):
    assert app_client.get("/credits/me").status_code == 401


def test_without_account_returns_initial_and_writes_nothing(app_client, db_session):
    ensure_users(db_session, "credits_r1")
    db_session.commit()

    r = _client(app_client, "credits_r1").get("/credits/me")

    assert r.status_code == 200
    assert r.json() == {"balance": INITIAL_CREDITS, "prices": PRICES, "review_reward": REVIEW_REWARD}
    assert db_session.execute(select(CreditAccount).where(CreditAccount.user_id == "credits_r1")).first() is None


def test_returns_balance_after_charge(app_client, db_session):
    ensure_users(db_session, "credits_r2")
    left = api.charge(db_session, user_id="credits_r2", feature="recommend_run", run_id=str(uuid.uuid4()))
    db_session.commit()

    assert _client(app_client, "credits_r2").get("/credits/me").json()["balance"] == left


def test_guest_is_403_with_initial_credits(app_client, db_session):
    create_guest(db_session, "credits_rg")
    db_session.commit()

    r = _client(app_client, "credits_rg").get("/credits/me")

    assert r.status_code == 403
    assert r.json()["code"] == "GUEST_NOT_ALLOWED"
    assert r.json()["detail"] == {"initial_credits": INITIAL_CREDITS}
    assert db_session.execute(select(CreditAccount).where(CreditAccount.user_id == "credits_rg")).first() is None

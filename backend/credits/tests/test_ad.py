"""광고 보고 충전 — docs/credits-reviews.md 3.7절, 12절 25~31(#1038).

service를 직접 부르고 시각(now)을 주입한다. HTTP 경로는 아래 「라우터」 절에서 main.app으로 태운다.
값은 credits/constants.py에서 읽는다(테스트에 다시 적지 않는다).
"""

import dataclasses
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from auth.testing import create_guest, ensure_users, session_cookie
from common.errors import AppError
from common.settings import ConfigError, Settings
from credits import api, core, service
from credits.constants import (
    AD_DAILY_MAX, AD_MIN_WATCH_S, AD_REWARD, AD_SESSION_TTL_S, INITIAL_CREDITS, MAX_BALANCE, PRICES,
)
from credits.models import CreditAccount, CreditAdSession, CreditLedger

T0 = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)   # KST 12:00


def _s(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


def _drain(db, user_id) -> None:
    """잔액이 가장 싼 가격보다 적어질 때까지 추천을 차감한다(원장과 balance가 맞는 채로)."""
    while api.get_balance(db, user_id=user_id) >= PRICES["recommend_run"]:
        api.charge(db, user_id=user_id, feature="recommend_run", run_id=str(uuid.uuid4()))


def _ad(db, user_id, now=T0) -> dict:
    return service.get_my_credits(db, user_id=user_id, now=now)["ad"]


def _open(db, user_id, now=T0) -> dict:
    return service.open_ad_session(db, user_id=user_id, now=now)


def _claim(db, user_id, session_id, now) -> dict:
    return service.claim_ad_session(db, user_id=user_id, ad_session_id=str(session_id), now=now)


def _error(fn, *args) -> AppError:
    with pytest.raises(AppError) as caught:
        fn(*args)
    return caught.value


def _ad_ledger(db, user_id):
    return db.execute(select(CreditLedger.delta, CreditLedger.ref_id)
                      .where(CreditLedger.user_id == user_id, CreditLedger.reason == "ad")).all()


def _sessions(db, user_id) -> int:
    return db.execute(select(func.count()).select_from(CreditAdSession)
                      .where(CreditAdSession.user_id == user_id)).scalar_one()


def _balance_matches_ledger(db, user_id) -> bool:
    balance = db.execute(select(CreditAccount.balance).where(CreditAccount.user_id == user_id)).scalar_one()
    total = db.execute(select(func.sum(CreditLedger.delta)).where(CreditLedger.user_id == user_id)).scalar_one()
    return balance == total


@pytest.fixture()
def user(db_session):
    ensure_users(db_session, "credits_ad1")
    return "credits_ad1"


@pytest.fixture()
def empty(db_session, user, ad_on):
    """광고가 켜져 있고 잔액이 0인 정식 계정."""
    _drain(db_session, user)
    return user


# core -------------------------------------------------------------------------------------------------------------

def test_core_ad_rules():
    assert core.ad_ref("abc") == "ad:abc"
    cheapest = min(PRICES.values())
    assert core.ad_needed(cheapest - 1) and not core.ad_needed(cheapest)
    assert core.claim_wait_s(T0, T0) == AD_MIN_WATCH_S
    assert core.claim_wait_s(T0, T0 + _s(AD_MIN_WATCH_S - 1.2)) == 2         # 올림
    assert core.claim_wait_s(T0, T0 + _s(AD_MIN_WATCH_S + 30)) == 0          # 0 아래로 가지 않는다
    assert not core.is_expired(T0, T0 + _s(AD_SESSION_TTL_S - 1))
    assert core.is_expired(T0, T0 + _s(AD_SESSION_TTL_S))


# 설정 -------------------------------------------------------------------------------------------------------------

def _settings(**kw) -> Settings:
    base = dict(environment="test", database_url="postgresql://x/y", cors_allow_origins=(), cors_allow_origin_regex=None,
                session_secret="s", places_mode="dev", llm_mode="dev")
    return Settings(**{**base, **kw})


def test_settings_reject_unknown_provider_and_fake_in_prod():
    assert _settings(credit_ad_provider="fake").credit_ad_provider == "fake"
    with pytest.raises(ConfigError, match="CREDIT_AD_PROVIDER"):
        _settings(credit_ad_provider="admob")
    prod = dict(environment="prod", cors_allow_origins=("https://pingo.example",), session_secret="real-secret",
                frontend_base_url="https://pingo.example", places_mode="real", llm_mode="real",
                kakao_client_id="k", kakao_client_secret="k", kakao_redirect_uri="k",
                elice_ml_api_base_url="e", elice_ml_api_key="e")
    with pytest.raises(ConfigError, match="CREDIT_AD_PROVIDER=fake"):
        _settings(**prod, credit_ad_provider="fake")
    assert _settings(**prod, credit_ad_provider="adsense").credit_ad_provider == "adsense"


# 25 ---------------------------------------------------------------------------------------------------------------

def test_off_is_not_available_and_open_is_409_off(db_session, user, ad_off):
    _drain(db_session, user)

    assert _ad(db_session, user) == {"available": False, "reward": AD_REWARD, "used_today": 0,
                                     "daily_max": AD_DAILY_MAX, "provider": None, "unit_id": None}
    err = _error(_open, db_session, user)
    assert (err.code, err.detail) == ("AD_REWARD_UNAVAILABLE", {"reason": "off"})
    assert _sessions(db_session, user) == 0


def test_provider_and_unit_id_are_passed_through(db_session, user, monkeypatch):
    monkeypatch.setattr(service, "settings", dataclasses.replace(service.settings, credit_ad_provider="adsense",
                                                                 credit_ad_unit_id="ca-pub-1/2"))
    ad = _ad(db_session, user)
    assert (ad["provider"], ad["unit_id"]) == ("adsense", "ca-pub-1/2")


# 26 ---------------------------------------------------------------------------------------------------------------

def test_balance_at_or_above_cheapest_price_is_not_needed(db_session, user, ad_on):
    assert _ad(db_session, user)["available"] is False                      # 계정 없음 = 처음 지급량
    while api.get_balance(db_session, user_id=user) > min(PRICES.values()):
        api.charge(db_session, user_id=user, feature="recommend_run", run_id=str(uuid.uuid4()))

    assert _ad(db_session, user)["available"] is False
    err = _error(_open, db_session, user)
    assert (err.code, err.detail) == ("AD_REWARD_UNAVAILABLE", {"reason": "not_needed"})


def test_empty_balance_is_available(db_session, empty):
    assert _ad(db_session, empty) == {"available": True, "reward": AD_REWARD, "used_today": 0,
                                      "daily_max": AD_DAILY_MAX, "provider": "fake", "unit_id": None}


# 27 ---------------------------------------------------------------------------------------------------------------

def test_daily_limit_resets_at_kst_midnight(db_session, empty):
    """KST 자정 = 15:00Z. 15분마다 열면 앞 세션이 만료돼 새 세션이 된다(받지 않아 잔액은 0 그대로)."""
    start = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
    opened = [_open(db_session, empty, start + _s(AD_SESSION_TTL_S * i))["ad_session_id"] for i in range(AD_DAILY_MAX)]
    assert len(set(opened)) == AD_DAILY_MAX

    for late in (start + _s(AD_SESSION_TTL_S * AD_DAILY_MAX), datetime(2026, 11, 2, 14, 59, 59, tzinfo=timezone.utc)):
        err = _error(_open, db_session, empty, late)
        assert (err.code, err.detail) == ("AD_REWARD_LIMIT", {"limit": AD_DAILY_MAX})
        assert _ad(db_session, empty, late)["available"] is False

    midnight = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    assert _ad(db_session, empty, midnight)["used_today"] == 0
    assert _open(db_session, empty, midnight)["ad_session_id"] not in opened
    assert _ad(db_session, empty, midnight)["used_today"] == 1


# 28 ---------------------------------------------------------------------------------------------------------------

def test_reopening_returns_the_unclaimed_session_without_using_a_count(db_session, empty):
    first = _open(db_session, empty)
    again = _open(db_session, empty, T0 + _s(3))

    assert first == {"ad_session_id": first["ad_session_id"], "claim_after_s": AD_MIN_WATCH_S}
    assert again == {"ad_session_id": first["ad_session_id"], "claim_after_s": AD_MIN_WATCH_S - 3}
    assert _ad(db_session, empty, T0 + _s(3))["used_today"] == 1


def test_unclaimed_session_is_resumed_before_balance_and_limit_checks(db_session, empty):
    """연 사이에 잔액이 올라도(후기) 받지 않은 세션은 이어 준다 — 잔액·횟수 검사보다 먼저 본다."""
    first = _open(db_session, empty)
    api.grant_review(db_session, user_id=empty, place_id="p1")

    assert _open(db_session, empty, T0 + _s(1))["ad_session_id"] == first["ad_session_id"]


# 29 ---------------------------------------------------------------------------------------------------------------

def test_claim_before_min_watch_is_too_early_then_credits(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]

    err = _error(_claim, db_session, empty, sid, T0 + _s(3))
    assert (err.code, err.detail) == ("AD_REWARD_INVALID", {"reason": "too_early", "retry_after_s": AD_MIN_WATCH_S - 3})

    assert _claim(db_session, empty, sid, T0 + _s(AD_MIN_WATCH_S)) == {"credited": AD_REWARD, "balance": AD_REWARD}
    assert _ad_ledger(db_session, empty) == [(AD_REWARD, f"ad:{sid}")]
    assert api.get_balance(db_session, user_id=empty) == AD_REWARD


# 30 ---------------------------------------------------------------------------------------------------------------

def test_claim_twice_returns_the_first_result_once(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]
    first = _claim(db_session, empty, sid, T0 + _s(AD_MIN_WATCH_S))
    api.charge(db_session, user_id=empty, feature="recommend_run", run_id=str(uuid.uuid4()))

    again = _claim(db_session, empty, sid, T0 + _s(AD_SESSION_TTL_S * 2))   # 만료 뒤에도 받은 결과는 그대로

    assert again == {"credited": first["credited"], "balance": first["balance"] - PRICES["recommend_run"]}
    assert len(_ad_ledger(db_session, empty)) == 1


def test_claiming_someone_elses_or_unknown_session_is_404(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]
    ensure_users(db_session, "credits_ad2")

    for who, target in (("credits_ad2", sid), (empty, uuid.uuid4()), (empty, "not-a-uuid")):
        assert _error(_claim, db_session, who, target, T0 + _s(AD_MIN_WATCH_S)).code == "NOT_FOUND"
    assert _ad_ledger(db_session, empty) == []


def test_claim_after_ttl_is_expired_and_a_new_session_opens(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]
    late = T0 + _s(AD_SESSION_TTL_S)

    err = _error(_claim, db_session, empty, sid, late)
    assert (err.code, err.detail) == ("AD_REWARD_INVALID", {"reason": "expired"})
    assert _ad_ledger(db_session, empty) == []
    assert _open(db_session, empty, late)["ad_session_id"] != sid
    assert _ad(db_session, empty, late)["used_today"] == 2


# 31 ---------------------------------------------------------------------------------------------------------------

def test_claim_fills_only_up_to_max_when_reviews_raised_the_balance(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]
    for place in ("p1", "p2", "p3"):                       # 0 → 10 → 20 → 30(상한)
        api.grant_review(db_session, user_id=empty, place_id=place)
    target = MAX_BALANCE - AD_REWARD // 2
    while api.get_balance(db_session, user_id=empty) > target:
        api.charge(db_session, user_id=empty, feature="recommend_run", run_id=str(uuid.uuid4()))

    got = _claim(db_session, empty, sid, T0 + _s(AD_MIN_WATCH_S))

    assert got == {"credited": MAX_BALANCE - target, "balance": MAX_BALANCE}
    assert _ad_ledger(db_session, empty) == [(MAX_BALANCE - target, f"ad:{sid}")]


def test_claim_at_max_still_leaves_a_zero_line(db_session, empty):
    sid = _open(db_session, empty)["ad_session_id"]
    for place in ("p1", "p2", "p3"):
        api.grant_review(db_session, user_id=empty, place_id=place)

    assert _claim(db_session, empty, sid, T0 + _s(AD_MIN_WATCH_S)) == {"credited": 0, "balance": MAX_BALANCE}
    assert _ad_ledger(db_session, empty) == [(0, f"ad:{sid}")]
    assert _claim(db_session, empty, sid, T0 + _s(60))["credited"] == 0


def test_guest_cannot_open_or_claim_and_leaves_no_rows(db_session, ad_on):
    guest = create_guest(db_session, "credits_adg").id
    owner = "credits_ad3"
    ensure_users(db_session, owner)
    _drain(db_session, owner)
    sid = _open(db_session, owner)["ad_session_id"]

    for fn, args in ((_open, (db_session, guest)), (_claim, (db_session, guest, sid, T0 + _s(AD_MIN_WATCH_S)))):
        err = _error(fn, *args)
        assert (err.code, err.detail) == ("GUEST_NOT_ALLOWED", {"initial_credits": INITIAL_CREDITS})
    assert _sessions(db_session, guest) == 0
    assert db_session.execute(select(CreditAccount).where(CreditAccount.user_id == guest)).first() is None


def test_balance_equals_ledger_sum_with_ad_lines(db_session, empty):
    """명세 12절 8을 ad 줄과 함께 — 받기, 상한에 걸린 받기, 차감을 섞는다."""
    now = T0
    for _ in range(AD_DAILY_MAX):
        sid = _open(db_session, empty, now)["ad_session_id"]
        now += _s(AD_MIN_WATCH_S)
        _claim(db_session, empty, sid, now)
        _drain(db_session, empty)
    assert _balance_matches_ledger(db_session, empty)
    assert len(_ad_ledger(db_session, empty)) == AD_DAILY_MAX


# 계정 수명 ---------------------------------------------------------------------------------------------------------

def test_delete_and_reassign_remove_ad_sessions(db_session, empty):
    _open(db_session, empty)
    stray = "credits_ad_stray"
    _drain(db_session, stray)
    _open(db_session, stray)

    assert api.reassign_user(db_session, from_user_id=stray, to_user_id=empty)["credit_ad_sessions"] == 1
    assert _sessions(db_session, stray) == 0 and _sessions(db_session, empty) == 1
    api.delete_by_user(db_session, user_id=empty)
    assert _sessions(db_session, empty) == 0


# 라우터 -----------------------------------------------------------------------------------------------------------

def _client(app_client, user_id):
    return TestClient(app_client.app, cookies=session_cookie(user_id))


def test_http_open_and_claim(app_client, db_session, ad_on):
    ensure_users(db_session, "credits_adr")
    _drain(db_session, "credits_adr")
    db_session.commit()
    c = _client(app_client, "credits_adr")

    assert c.get("/credits/me").json()["ad"]["available"] is True
    opened = c.post("/credits/ad-sessions")
    assert opened.status_code == 201 and opened.json()["claim_after_s"] == AD_MIN_WATCH_S
    sid = opened.json()["ad_session_id"]

    early = c.post(f"/credits/ad-sessions/{sid}/claim")
    assert early.status_code == 409 and early.json()["detail"]["reason"] == "too_early"

    db_session.execute(update(CreditAdSession).where(CreditAdSession.id == uuid.UUID(sid))
                       .values(issued_at=func.now() - _s(AD_MIN_WATCH_S + 1)))
    db_session.commit()
    claimed = c.post(f"/credits/ad-sessions/{sid}/claim")
    assert claimed.status_code == 200 and claimed.json() == {"credited": AD_REWARD, "balance": AD_REWARD}
    assert c.post(f"/credits/ad-sessions/{sid}/claim").json() == claimed.json()

    me = c.get("/credits/me").json()
    assert me["balance"] == AD_REWARD and me["ad"]["used_today"] == 1 and me["ad"]["available"] is False
    assert c.post(f"/credits/ad-sessions/{uuid.uuid4()}/claim").status_code == 404


def test_http_requires_login(app_client):
    assert app_client.post("/credits/ad-sessions").status_code == 401
    assert app_client.post(f"/credits/ad-sessions/{uuid.uuid4()}/claim").status_code == 401

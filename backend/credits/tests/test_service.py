"""credits.api — docs/credits-reviews.md 12절 2~8. 1, 4의 GET은 test_router.py.

값은 credits/constants.py에서 읽는다(가격표를 테스트에 다시 적지 않는다).
"""

import threading
import uuid

import pytest
from sqlalchemy import func, select

from auth.testing import create_guest, ensure_users
from common.errors import AppError
from credits import api
from credits.constants import INITIAL_CREDITS, PRICES, REVIEW_REWARD
from credits.models import CreditAccount, CreditLedger

RUN = "recommend_run"
COURSE = "course"


def _run_id() -> str:
    return str(uuid.uuid4())


def _account(db, user_id):
    return db.execute(select(CreditAccount).where(CreditAccount.user_id == user_id)).scalar_one_or_none()


def _ledger(db, user_id):
    """그 사람의 원장 줄. 같은 트랜잭션의 줄은 created_at이 같아 순서가 없다 — 단언은 순서와 무관하게 한다."""
    return db.execute(select(CreditLedger.reason, CreditLedger.delta, CreditLedger.ref_id)
                      .where(CreditLedger.user_id == user_id)).all()


def _drain(db, user_id) -> None:
    """잔액이 가격보다 적어질 때까지 추천을 차감한다(원장과 balance가 맞는 채로 0을 만든다)."""
    while True:
        try:
            api.charge(db, user_id=user_id, feature=RUN, run_id=_run_id())
        except AppError:
            return


@pytest.fixture()
def user(db_session):
    ensure_users(db_session, "credits_u1")
    return "credits_u1"


@pytest.fixture()
def guest(db_session):
    return create_guest(db_session, "credits_g1").id


# 2 ---------------------------------------------------------------------------------------------------------------

def test_first_charge_creates_account_with_initial_then_spends(db_session, user):
    run_id = _run_id()

    left = api.charge(db_session, user_id=user, feature=RUN, run_id=run_id)

    assert left == INITIAL_CREDITS - PRICES[RUN]
    assert _account(db_session, user).balance == left
    assert {(r.reason, r.delta, r.ref_id) for r in _ledger(db_session, user)} == {
        ("initial", INITIAL_CREDITS, f"initial:{user}"),
        ("spend", -PRICES[RUN], f"{RUN}:{run_id}"),
    }


def test_same_run_is_charged_once(db_session, user):
    run_id = _run_id()
    first = api.charge(db_session, user_id=user, feature=RUN, run_id=run_id)

    again = api.charge(db_session, user_id=user, feature=RUN, run_id=run_id)

    assert again == first
    assert len([r for r in _ledger(db_session, user) if r.reason == "spend"]) == 1


def test_concurrent_first_charges_grant_initial_once(factory, committed_user):
    """처음 쓰는 요청 둘이 동시에 와도 initial은 한 번이다(INSERT ... ON CONFLICT DO NOTHING, 명세 3.4)."""
    barrier = threading.Barrier(2)
    errors = []

    def worker():
        with factory() as s:
            try:
                barrier.wait()
                api.charge(s, user_id=committed_user, feature=RUN, run_id=_run_id())
                s.commit()
            except Exception as exc:  # noqa: BLE001 — 스레드 안의 실패를 본 스레드에서 단언한다
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    with factory() as s:
        reasons = [r.reason for r in _ledger(s, committed_user)]
        assert reasons.count("initial") == 1 and reasons.count("spend") == 2
        assert _account(s, committed_user).balance == INITIAL_CREDITS - 2 * PRICES[RUN]


# 3 ---------------------------------------------------------------------------------------------------------------

def test_zero_balance_is_402_for_check_and_charge(db_session, user):
    _drain(db_session, user)
    balance = _account(db_session, user).balance
    assert balance < PRICES[RUN]

    with pytest.raises(AppError) as checked:
        api.check_can_spend(db_session, user_id=user, feature=RUN)
    with pytest.raises(AppError) as charged:
        api.charge(db_session, user_id=user, feature=RUN, run_id=_run_id())

    for err in (checked.value, charged.value):
        assert (err.code, err.status) == ("CREDIT_INSUFFICIENT", 402)
        assert err.detail == {"required": PRICES[RUN], "balance": balance}


def test_check_can_spend_reads_only(db_session, user):
    api.check_can_spend(db_session, user_id=user, feature=RUN)

    assert _account(db_session, user) is None
    assert _ledger(db_session, user) == []


def test_unknown_feature_is_a_programming_error(db_session, user):
    with pytest.raises(ValueError):
        api.check_can_spend(db_session, user_id=user, feature="evidence_add")
    with pytest.raises(ValueError):
        api.charge(db_session, user_id=user, feature="evidence_add", run_id=_run_id())


# 4 ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda db, uid: api.check_can_spend(db, user_id=uid, feature=RUN),
    lambda db, uid: api.charge(db, user_id=uid, feature=COURSE, run_id=_run_id()),
])
def test_guest_is_403_with_initial_credits_and_gets_no_account(db_session, guest, call):
    with pytest.raises(AppError) as exc:
        call(db_session, guest)

    assert (exc.value.code, exc.value.status) == ("GUEST_NOT_ALLOWED", 403)
    assert exc.value.detail == {"initial_credits": INITIAL_CREDITS}
    assert _account(db_session, guest) is None


def test_guest_review_reward_is_zero_without_account(db_session, guest):
    assert api.grant_review(db_session, user_id=guest, place_id="p1") == 0
    assert _account(db_session, guest) is None


# 5 ---------------------------------------------------------------------------------------------------------------

def test_refund_twice_returns_once(db_session, user):
    run_id = _run_id()
    api.charge(db_session, user_id=user, feature=COURSE, run_id=run_id)

    assert api.refund(db_session, feature=COURSE, run_id=run_id) is True
    assert api.refund(db_session, feature=COURSE, run_id=run_id) is False

    assert _account(db_session, user).balance == INITIAL_CREDITS
    assert [r.ref_id for r in _ledger(db_session, user) if r.reason == "refund"] == [f"refund:{COURSE}:{run_id}"]


def test_refund_without_charge_is_false(db_session, user):
    assert api.refund(db_session, feature=COURSE, run_id=_run_id()) is False
    assert _account(db_session, user) is None


def test_refund_matches_feature(db_session, user):
    """같은 run id라도 다른 feature의 차감은 돌려주지 않는다."""
    run_id = _run_id()
    api.charge(db_session, user_id=user, feature=RUN, run_id=run_id)

    assert api.refund(db_session, feature=COURSE, run_id=run_id) is False


# 6 ---------------------------------------------------------------------------------------------------------------

def test_review_reward_once_per_place(db_session, user):
    assert api.grant_review(db_session, user_id=user, place_id="p1") == REVIEW_REWARD
    assert api.grant_review(db_session, user_id=user, place_id="p1") == 0
    assert api.grant_review(db_session, user_id=user, place_id="p2") == REVIEW_REWARD

    assert _account(db_session, user).balance == INITIAL_CREDITS + 2 * REVIEW_REWARD


# 7 ---------------------------------------------------------------------------------------------------------------

def test_delete_by_user_removes_account_and_ledger(db_session, user):
    api.charge(db_session, user_id=user, feature=RUN, run_id=_run_id())
    api.grant_review(db_session, user_id=user, place_id="p1")

    assert api.delete_by_user(db_session, user_id=user) == 1 + 3   # 계정 1 + initial, spend, review

    assert _account(db_session, user) is None
    assert _ledger(db_session, user) == []
    assert api.delete_by_user(db_session, user_id=user) == 0   # 멱등


def test_reassign_user_deletes_guest_rows_and_keeps_target(db_session, user):
    """게스트 쪽 행이 있어도 옮기지 않고 지운다 — 옮기면 initial이 두 번 들어간다."""
    stray = "credits_stray_guest"   # 게스트 판정 전의 행을 흉내 낸다(users 행 없음)
    api.charge(db_session, user_id=stray, feature=RUN, run_id=_run_id())
    target_balance = api.charge(db_session, user_id=user, feature=RUN, run_id=_run_id())

    moved = api.reassign_user(db_session, from_user_id=stray, to_user_id=user)

    assert moved == {"credit_accounts": 1, "credit_ledger": 2}
    assert _account(db_session, stray) is None and _ledger(db_session, stray) == []
    assert _account(db_session, user).balance == target_balance
    assert [r.reason for r in _ledger(db_session, user)].count("initial") == 1
    assert api.reassign_user(db_session, from_user_id=stray, to_user_id=user) == {"credit_accounts": 0, "credit_ledger": 0}


def test_reassign_same_id_is_noop(db_session, user):
    api.charge(db_session, user_id=user, feature=RUN, run_id=_run_id())

    assert api.reassign_user(db_session, from_user_id=user, to_user_id=user) == {"credit_ledger": 0, "credit_accounts": 0}
    assert _account(db_session, user) is not None


def test_refund_after_withdrawal_is_false(db_session, user):
    run_id = _run_id()
    api.charge(db_session, user_id=user, feature=COURSE, run_id=run_id)
    api.delete_by_user(db_session, user_id=user)

    assert api.refund(db_session, feature=COURSE, run_id=run_id) is False
    assert _account(db_session, user) is None


# 8 ---------------------------------------------------------------------------------------------------------------

def test_balance_equals_ledger_sum_after_mixed_operations(db_session):
    """원본은 원장이다 — 차감·환불·보상·부족 실패를 섞어 돌린 뒤 사람마다 balance = 원장 delta 합(명세 3.4)."""
    ensure_users(db_session, "credits_m1", "credits_m2")
    users = ["credits_m1", "credits_m2"]
    course_runs = []
    for i in range(12):
        uid = users[i % 2]
        api.charge(db_session, user_id=uid, feature=RUN, run_id=_run_id())
        run_id = _run_id()
        api.charge(db_session, user_id=uid, feature=COURSE, run_id=run_id)
        course_runs.append(run_id)
        api.grant_review(db_session, user_id=uid, place_id=f"p{i % 3}")
    for run_id in course_runs[::3]:
        api.refund(db_session, feature=COURSE, run_id=run_id)
        api.refund(db_session, feature=COURSE, run_id=run_id)
    _drain(db_session, users[0])

    for uid in users:
        total = db_session.execute(select(func.sum(CreditLedger.delta)).where(CreditLedger.user_id == uid)).scalar_one()
        assert _account(db_session, uid).balance == total

"""
크레딧 잔액·원장 (docs/credits-reviews.md 3절, 8절). 커밋하지 않는다 — 부르는 쪽의 트랜잭션에 얹힌다.

잔액이 바뀌는 길은 `_apply` 하나다. 그 사람의 계정 행을 잡고(없으면 만들면서 initial +30), 원장 한 줄과 balance를 같이
바꾼다. 같은 사람의 차감·환불·보상은 계정 행 잠금(SELECT ... FOR UPDATE)에서 줄을 선다.
게스트 판정은 auth.api.guest_user_ids 한 곳(명세 3.1). 게스트에는 계정을 만들지 않는다.
"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import api as auth_api
from common.errors import AppError
from credits import core
from credits.constants import INITIAL_CREDITS, PRICES, REVIEW_REWARD
from credits.models import CreditAccount, CreditLedger


def _is_guest(db: Session, user_id: str) -> bool:
    return user_id in auth_api.guest_user_ids(db, [user_id])


def _reject_guest(db: Session, user_id: str) -> None:
    if _is_guest(db, user_id):
        raise AppError("GUEST_NOT_ALLOWED", detail={"initial_credits": INITIAL_CREDITS})


def _insufficient(required: int, balance: int) -> AppError:
    return AppError("CREDIT_INSUFFICIENT", detail={"required": required, "balance": balance})


def balance_of(db: Session, *, user_id: str) -> int:
    """읽기만. 계정 행이 없으면 INITIAL_CREDITS(행을 만들지 않는다)."""
    balance = db.execute(select(CreditAccount.balance).where(CreditAccount.user_id == user_id)).scalar_one_or_none()
    return INITIAL_CREDITS if balance is None else balance


def get_my_credits(db: Session, *, user_id: str) -> dict:
    """GET /credits/me — 게스트는 403. 쓰지 않는다."""
    _reject_guest(db, user_id)
    return {"balance": balance_of(db, user_id=user_id), "prices": dict(PRICES), "review_reward": REVIEW_REWARD}


def check_can_spend(db: Session, *, user_id: str, feature: str) -> None:
    """모델 호출 전 읽기 확인. 게스트 403, 잔액 < 가격 402."""
    price = core.price_of(feature)
    _reject_guest(db, user_id)
    balance = balance_of(db, user_id=user_id)
    if balance < price:
        raise _insufficient(price, balance)


def _lock_account(db: Session, user_id: str) -> int:
    """그 사람의 계정 행을 잡고 잔액을 돌려준다. 없으면 만들고 원장에 initial을 남긴다.
    INSERT ... ON CONFLICT DO NOTHING RETURNING이라 동시에 처음 쓰는 요청이 둘이어도 initial은 한 번이다(명세 3.4)."""
    created = db.execute(
        insert(CreditAccount).values(user_id=user_id, balance=INITIAL_CREDITS)
        .on_conflict_do_nothing(index_elements=[CreditAccount.user_id])
        .returning(CreditAccount.user_id)
    ).scalar_one_or_none()
    if created is not None:
        db.execute(insert(CreditLedger).values(user_id=user_id, delta=INITIAL_CREDITS, reason="initial",
                                               ref_id=core.initial_ref(user_id)))
    return db.execute(
        select(CreditAccount.balance).where(CreditAccount.user_id == user_id).with_for_update()
    ).scalar_one()


def _ledger_has(db: Session, ref_id: str) -> bool:
    return db.execute(select(CreditLedger.id).where(CreditLedger.ref_id == ref_id)).first() is not None


def _apply(db: Session, *, user_id: str, balance: int, delta: int, reason: str, ref_id: str) -> int:
    """잠근 계정에 원장 한 줄과 balance를 같이 더한다. 새 잔액."""
    db.execute(insert(CreditLedger).values(user_id=user_id, delta=delta, reason=reason, ref_id=ref_id))
    db.execute(update(CreditAccount).where(CreditAccount.user_id == user_id)
               .values(balance=CreditAccount.balance + delta, updated_at=func.now()))
    return balance + delta


def charge(db: Session, *, user_id: str, feature: str, run_id: str) -> int:
    """실행 저장과 같은 트랜잭션에서 가격만큼 뺀다. 남은 잔액. 같은 run을 두 번 부르면 두 번째는 빼지 않는다."""
    price = core.price_of(feature)
    _reject_guest(db, user_id)
    balance = _lock_account(db, user_id)
    ref_id = core.spend_ref(feature, run_id)
    if _ledger_has(db, ref_id):
        return balance
    if balance < price:
        raise _insufficient(price, balance)
    return _apply(db, user_id=user_id, balance=balance, delta=-price, reason="spend", ref_id=ref_id)


def refund(db: Session, *, feature: str, run_id: str) -> bool:
    """그 run의 차감을 돌려준다. 차감이 없었거나(또는 탈퇴로 지워졌거나) 이미 돌려줬으면 False."""
    spend = core.spend_ref(feature, run_id)
    row = db.execute(select(CreditLedger.user_id, CreditLedger.delta).where(CreditLedger.ref_id == spend)).first()
    if row is None:
        return False
    balance = db.execute(
        select(CreditAccount.balance).where(CreditAccount.user_id == row.user_id).with_for_update()
    ).scalar_one_or_none()
    refund_id = core.refund_ref(spend)
    if balance is None or _ledger_has(db, refund_id):
        return False
    _apply(db, user_id=row.user_id, balance=balance, delta=-row.delta, reason="refund", ref_id=refund_id)
    return True


def grant_review(db: Session, *, user_id: str, place_id: str) -> int:
    """그 장소 첫 후기 보상. 받은 크레딧(REVIEW_REWARD 또는 0). 게스트는 0이고 계정을 만들지 않는다."""
    if _is_guest(db, user_id):
        return 0
    balance = _lock_account(db, user_id)
    ref_id = core.review_ref(user_id, place_id)
    if _ledger_has(db, ref_id):
        return 0
    _apply(db, user_id=user_id, balance=balance, delta=REVIEW_REWARD, reason="review", ref_id=ref_id)
    return REVIEW_REWARD


def _delete_user_rows(db: Session, user_id: str) -> dict[str, int]:
    """테이블 이름 → 지운 행 수."""
    return {
        "credit_ledger": db.execute(delete(CreditLedger).where(CreditLedger.user_id == user_id)).rowcount,
        "credit_accounts": db.execute(delete(CreditAccount).where(CreditAccount.user_id == user_id)).rowcount,
    }


def delete_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴 — 그 사람의 계정과 원장을 지운다. 지운 행 수."""
    return sum(_delete_user_rows(db, user_id).values())


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기 — 옮기지 않는다. 게스트는 계정이 없고, 혹시 있으면 지운다(초기 지급 두 번 방지, 명세 6절).
    테이블 이름 → 지운 행 수. 같은 id면 아무것도 하지 않는다."""
    if from_user_id == to_user_id:
        return {"credit_ledger": 0, "credit_accounts": 0}
    return _delete_user_rows(db, from_user_id)

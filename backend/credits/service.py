"""
크레딧 잔액·원장 (docs/credits-reviews.md 3절, 8절). 커밋하지 않는다 — 부르는 쪽의 트랜잭션에 얹힌다.

잔액이 바뀌는 길은 `_apply` 하나다. 그 사람의 계정 행을 잡고(없으면 만들면서 initial +30), 원장 한 줄과 balance를 같이
바꾼다. 같은 사람의 차감·환불·보상은 계정 행 잠금(SELECT ... FOR UPDATE)에서 줄을 선다.
게스트 판정은 auth.api.guest_user_ids 한 곳(명세 3.1). 게스트에는 계정을 만들지 않는다.

광고 보고 충전(명세 3.7, #1038)은 이 모듈 라우터 안에서 끝난다 — 세션을 열고(open_ad_session), 받는다(claim_ad_session).
받을 때도 잔액은 `_apply`로만 바뀐다. 시각(now)은 라우터가 한 번 만들어 넘긴다(테스트가 주입한다).
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import api as auth_api
from common.errors import AppError
from common.kst import kst_day_start
from common.settings import settings
from credits import core
from credits.constants import AD_DAILY_MAX, AD_REWARD, INITIAL_CREDITS, MAX_BALANCE, PRICES, REVIEW_REWARD
from credits.models import CreditAccount, CreditAdSession, CreditLedger


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


def get_my_credits(db: Session, *, user_id: str, now: datetime) -> dict:
    """GET /credits/me — 게스트는 403. 쓰지 않는다."""
    _reject_guest(db, user_id)
    balance = balance_of(db, user_id=user_id)
    return {"balance": balance, "max_balance": MAX_BALANCE, "prices": dict(PRICES),
            "review_reward": REVIEW_REWARD, "ad": _ad_status(db, user_id=user_id, balance=balance, now=now)}


# 광고 보고 충전 (명세 3.7) -----------------------------------------------------------------------------------------

def _ad_provider() -> str | None:
    """광고 제공자. 설정이 비어 있으면 None(꺼짐)."""
    return settings.credit_ad_provider or None


def _ad_used_today(db: Session, user_id: str, now: datetime) -> int:
    """오늘(KST) 연 세션 수 — 받았는지와 무관하게 연 것을 센다."""
    start = kst_day_start(now)
    return db.execute(
        select(func.count()).select_from(CreditAdSession)
        .where(CreditAdSession.user_id == user_id, CreditAdSession.issued_at >= start,
               CreditAdSession.issued_at < start + timedelta(days=1))
    ).scalar_one()


def _ad_status(db: Session, *, user_id: str, balance: int, now: datetime) -> dict:
    """GET /credits/me의 ad 블록(CreditAd). available은 명세 3.7 「언제 열리나」 2~4(1 게스트는 앞에서 403)."""
    provider = _ad_provider()
    used = _ad_used_today(db, user_id, now)
    return {
        "available": provider is not None and core.ad_needed(balance) and used < AD_DAILY_MAX,
        "reward": AD_REWARD,
        "used_today": used,
        "daily_max": AD_DAILY_MAX,
        "provider": provider,
        "unit_id": (settings.credit_ad_unit_id or None) if provider is not None else None,
    }


def _open_ad_session_of(db: Session, user_id: str, now: datetime) -> CreditAdSession | None:
    """받지 않았고 만료 전인 내 세션. 가장 최근 것이 만료면 그보다 먼저 연 것도 만료다."""
    latest = db.execute(
        select(CreditAdSession)
        .where(CreditAdSession.user_id == user_id, CreditAdSession.claimed_at.is_(None))
        .order_by(CreditAdSession.issued_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is None or core.is_expired(latest.issued_at, now):
        return None
    return latest


def open_ad_session(db: Session, *, user_id: str, now: datetime) -> dict:
    """POST /credits/ad-sessions → AdSession. 계정 행을 잡아 같은 사람의 열기를 줄 세운다.
    받지 않은 세션이 있으면 그것을 돌려준다 — 잔액·횟수 검사보다 먼저 본다(광고를 닫고 다시 눌러도 횟수가 줄지 않는다)."""
    _reject_guest(db, user_id)
    if _ad_provider() is None:
        raise AppError("AD_REWARD_UNAVAILABLE", detail={"reason": "off"})
    balance = _lock_account(db, user_id)
    pending = _open_ad_session_of(db, user_id, now)
    if pending is not None:
        return {"ad_session_id": pending.id, "claim_after_s": core.claim_wait_s(pending.issued_at, now)}
    if not core.ad_needed(balance):
        raise AppError("AD_REWARD_UNAVAILABLE", detail={"reason": "not_needed"})
    if _ad_used_today(db, user_id, now) >= AD_DAILY_MAX:
        raise AppError("AD_REWARD_LIMIT", detail={"limit": AD_DAILY_MAX})
    session_id = uuid.uuid4()
    db.execute(insert(CreditAdSession).values(id=session_id, user_id=user_id, issued_at=now))
    return {"ad_session_id": session_id, "claim_after_s": core.claim_wait_s(now, now)}


def claim_ad_session(db: Session, *, user_id: str, ad_session_id: str, now: datetime) -> dict:
    """POST /credits/ad-sessions/{id}/claim → AdClaim. 이미 받았으면 처음 credited를 그대로 돌려준다(멱등).
    받을 때 잔액 조건은 다시 보지 않는다 — 상한까지만 채운다(명세 3.6). 0이어도 원장 줄을 남긴다."""
    _reject_guest(db, user_id)
    try:
        target = uuid.UUID(ad_session_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    ad = db.execute(select(CreditAdSession).where(CreditAdSession.id == target).with_for_update()).scalar_one_or_none()
    if ad is None or ad.user_id != user_id:
        raise AppError("NOT_FOUND")
    if ad.claimed_at is not None:
        return {"credited": ad.credited, "balance": balance_of(db, user_id=user_id)}
    wait = core.claim_wait_s(ad.issued_at, now)
    if wait > 0:
        raise AppError("AD_REWARD_INVALID", detail={"reason": "too_early", "retry_after_s": wait})
    if core.is_expired(ad.issued_at, now):
        raise AppError("AD_REWARD_INVALID", detail={"reason": "expired"})
    balance = _lock_account(db, user_id)
    gain = core.capped_gain(AD_REWARD, balance)
    left = _apply(db, user_id=user_id, balance=balance, delta=gain, reason="ad", ref_id=core.ad_ref(ad.id))
    db.execute(update(CreditAdSession).where(CreditAdSession.id == ad.id).values(claimed_at=now, credited=gain))
    return {"credited": gain, "balance": left}


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
    """그 run의 차감을 돌려준다 — 잔액 상한까지만(명세 3.6). 상한에 걸려 0이어도 refund 줄을 남기고 True(멱등).
    차감이 없었거나(또는 7일 정리로 지워졌거나) 이미 돌려줬으면 False."""
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
    _apply(db, user_id=row.user_id, balance=balance, delta=core.capped_gain(-row.delta, balance), reason="refund",
           ref_id=refund_id)
    return True


def grant_review(db: Session, *, user_id: str, place_id: str) -> int:
    """그 장소 첫 후기 보상 — 잔액 상한까지만(명세 3.6). 받은 크레딧(0~REVIEW_REWARD). 게스트는 0이고 계정을 만들지 않는다.
    상한에 걸려 0이어도 원장에 그 장소 줄을 delta 0으로 남긴다 — 그 장소 보상은 끝이다(지웠다 다시 써서 받는 길을 막는다)."""
    if _is_guest(db, user_id):
        return 0
    balance = _lock_account(db, user_id)
    ref_id = core.review_ref(user_id, place_id)
    if _ledger_has(db, ref_id):
        return 0
    gain = core.capped_gain(REVIEW_REWARD, balance)
    _apply(db, user_id=user_id, balance=balance, delta=gain, reason="review", ref_id=ref_id)
    return gain


def _delete_user_rows(db: Session, user_id: str) -> dict[str, int]:
    """테이블 이름 → 지운 행 수."""
    return {
        "credit_ledger": db.execute(delete(CreditLedger).where(CreditLedger.user_id == user_id)).rowcount,
        "credit_accounts": db.execute(delete(CreditAccount).where(CreditAccount.user_id == user_id)).rowcount,
        "credit_ad_sessions": db.execute(delete(CreditAdSession).where(CreditAdSession.user_id == user_id)).rowcount,
    }


def delete_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴 7일 정리 — 그 사람의 계정, 원장, 광고 세션을 지운다. 지운 행 수."""
    return sum(_delete_user_rows(db, user_id).values())


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기 — 옮기지 않는다. 게스트는 계정이 없고, 혹시 있으면 지운다(초기 지급 두 번 방지, 명세 6절).
    테이블 이름 → 지운 행 수. 같은 id면 아무것도 하지 않는다."""
    if from_user_id == to_user_id:
        return {"credit_ledger": 0, "credit_accounts": 0, "credit_ad_sessions": 0}
    return _delete_user_rows(db, from_user_id)

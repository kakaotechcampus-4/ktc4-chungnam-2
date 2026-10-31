"""credits 공개 접점 — 다른 모듈은 이 파일만 부른다(#113, docs/credits-reviews.md 8절).

가격 숫자는 들지 않는다. feature 이름(= llm_calls.feature 라벨)만 넘기면 가격은 credits/constants.py에서 찾는다.
게스트 판정도 여기서 한다(auth.api.guest_user_ids) — 부르는 쪽이 is_guest를 넘기지 않는다. 모두 커밋하지 않는다.

부르는 곳(명세 8절):
- recommend `flows._create_run`(#949): 모델 전에 check_can_spend, run 저장과 같은 트랜잭션에서 charge
- agent.course(#950): run INSERT와 같은 트랜잭션에서 charge, 결과 없이 끝난 run에 refund
- reviews(#951): 첫 후기 저장과 같은 트랜잭션에서 grant_review
- reviews(#951): ReviewSaved.balance에 get_balance
- auth.service: 탈퇴 7일 정리 purge_withdrawn_user(delete_by_user), 게스트 합치기 MERGE_STEPS(reassign_user)
"""

from sqlalchemy.orm import Session

from credits import service


def check_can_spend(db: Session, *, user_id: str, feature: str) -> None:
    """읽기만. 게스트면 403 GUEST_NOT_ALLOWED(detail.initial_credits), 잔액 < 가격이면 402 CREDIT_INSUFFICIENT
    (detail.required, detail.balance). 모델 호출 전에 부른다. 가격표에 없는 feature는 ValueError."""
    service.check_can_spend(db, user_id=user_id, feature=feature)


def charge(db: Session, *, user_id: str, feature: str, run_id: str) -> int:
    """실행 저장과 같은 트랜잭션에서 가격만큼 뺀다. ref_id = f"{feature}:{run_id}". 남은 잔액.
    첫 쓰기면 계정을 만들고 initial을 남긴다. 같은 run으로 다시 부르면 빼지 않고 잔액만 돌려준다.
    읽기 확인과 쓰기 사이에 잔액이 줄었으면 여기서 402(모델은 이미 불렸다 — 드문 경합으로 받아들인다). 게스트는 403."""
    return service.charge(db, user_id=user_id, feature=feature, run_id=run_id)


def refund(db: Session, *, feature: str, run_id: str) -> bool:
    """결과 없이 끝난 실행의 차감을 돌려준다(코스 ENGINE_ERROR, INTERRUPTED). 멱등. 돌려줬으면 True,
    차감이 없었거나 이미 돌려줬으면 False."""
    return service.refund(db, feature=feature, run_id=run_id)


def grant_review(db: Session, *, user_id: str, place_id: str) -> int:
    """그 장소 첫 후기 보상. 받은 크레딧(REVIEW_REWARD 또는 0). 게스트면 0(호출 전에 reviews가 막는다)."""
    return service.grant_review(db, user_id=user_id, place_id=place_id)


def get_balance(db: Session, *, user_id: str) -> int:
    """읽기만. 지금 잔액. 계정 행이 없으면 INITIAL_CREDITS(행을 만들지 않는다). reviews가 ReviewSaved.balance를 채운다."""
    return service.balance_of(db, user_id=user_id)


def delete_by_user(db: Session, *, user_id: str) -> int:
    """계정과 원장을 지운다. 지운 행 수. 탈퇴 7일 뒤 정리(auth.service.purge_withdrawn_user)가 부른다 —
    탈퇴 때는 부르지 않는다(되살리면 잔액이 그대로 돌아와야 한다, #948)."""
    return service.delete_by_user(db, user_id=user_id)


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(auth.service.MERGE_STEPS)가 부른다 — 옮기지 않는다. 게스트는 계정이 없고, 혹시 있으면 지운다
    (옮기면 초기 지급이 두 번 된다). 테이블 이름 → 지운 행 수. 멱등, 같은 id면 아무것도 하지 않는다."""
    return service.reassign_user(db, from_user_id=from_user_id, to_user_id=to_user_id)

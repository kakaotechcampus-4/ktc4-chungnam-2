"""서비스 피드백 저장(#10). 저장만 하고 답장·알림은 없다."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from common.errors import AppError
from feedback.models import Feedback

MAX_MESSAGE_LEN = 1000


def clean_message(message: str) -> str:
    """앞뒤 공백을 지운 1~MAX_MESSAGE_LEN자. 아니면 VALIDATION_ERROR(422)."""
    text = message.strip()
    if not 1 <= len(text) <= MAX_MESSAGE_LEN:
        raise AppError("VALIDATION_ERROR", f"내용은 앞뒤 공백을 뺀 1~{MAX_MESSAGE_LEN}자여야 합니다")
    return text


def submit(db: Session, *, user_id: str, message: str, category: str, map_id: str | None) -> Feedback:
    row = Feedback(user_id=user_id, category=category, message=clean_message(message), map_id=map_id or None)
    db.add(row)
    db.flush()
    db.refresh(row)   # created_at(서버 기본값)을 읽어 온다
    return row


def anonymize_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴(#155) — 작성자 연결만 끊고 내용은 남긴다. 바꾼 행 수."""
    result = db.execute(update(Feedback).where(Feedback.user_id == user_id).values(user_id=None))
    return result.rowcount


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#560) — from_user의 피드백을 to_user로 옮긴다. 이미 NULL인 행은 건드리지 않는다. 테이블 → 옮긴 행 수."""
    if from_user_id == to_user_id:
        return {"feedback": 0}
    result = db.execute(update(Feedback).where(Feedback.user_id == from_user_id).values(user_id=to_user_id))
    return {"feedback": result.rowcount}

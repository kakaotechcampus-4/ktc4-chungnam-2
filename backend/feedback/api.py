"""다른 모듈이 feedback을 부르는 유일한 접점(docs/architecture.md §1.1)."""

from sqlalchemy.orm import Session

from common.errors import AppError
from common.ratelimit import SlidingWindowLimiter
from common.settings import settings
from feedback import service

submit_limiter = SlidingWindowLimiter(settings.feedback_per_hour, window_s=3600.0)   # 사용자당 시간당 상한, 인메모리


def check_submit_rate(user_id: str) -> None:
    if not submit_limiter.allow(user_id):
        raise AppError("RATE_LIMITED")


def anonymize_by_user(db: Session, *, user_id: str) -> int:
    """계정 탈퇴(#155)가 부른다 — 그 사용자의 피드백을 user_id NULL로 끊고 내용은 남긴다. 바꾼 행 수."""
    return service.anonymize_by_user(db, user_id=user_id)

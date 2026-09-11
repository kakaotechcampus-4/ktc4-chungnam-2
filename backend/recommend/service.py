"""
얇은 I/O 셸 — DB 접근만 한다(docs/code-quality.md). 판단은 core.py에, 다른 모듈 접근
(authz/pins.api)은 flows.py에 둔다.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from common.errors import AppError
from recommend.models import Candidate, RecommendRun


def load_candidate_with_run(db: Session, candidate_id: str) -> tuple[Candidate, RecommendRun]:
    """candidate와 그 run을 함께 읽는다. candidate가 없거나(형식 오류 포함) run 자체가
    없으면(정합성 버그 — 있어선 안 되지만 사용자에게 다른 코드를 보여줄 이유가 없다)
    404 NOT_FOUND(pins.service.get_pin_or_404와 같은 패턴)."""
    try:
        candidate_uuid = uuid.UUID(candidate_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    candidate = db.execute(
        select(Candidate).where(Candidate.id == candidate_uuid)
    ).scalar_one_or_none()
    if candidate is None:
        raise AppError("NOT_FOUND")
    run = db.execute(
        select(RecommendRun).where(RecommendRun.id == candidate.run_id)
    ).scalar_one_or_none()
    if run is None:
        raise AppError("NOT_FOUND")
    return candidate, run


def link_published_pin(db: Session, *, candidate_id: str, pin_id: str) -> None:
    """가드 UPDATE — WHERE published_pin_id IS NULL(mentor-review-plan.md "레이스 2번").
    rowcount==0이면 다른 경로로 이미 링크된 것 → 409 IDEMPOTENCY_CONFLICT, 호출부(flows.py)가
    커밋 전이라 이 예외로 인한 전체 롤백이 직전 pins INSERT까지 되돌린다."""
    result = db.execute(
        update(Candidate)
        .where(Candidate.id == uuid.UUID(candidate_id), Candidate.published_pin_id.is_(None))
        .values(published_pin_id=uuid.UUID(pin_id))
    )
    if result.rowcount == 0:
        raise AppError("IDEMPOTENCY_CONFLICT")

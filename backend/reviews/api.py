"""reviews 공개 접점 — 다른 모듈은 이 파일만 부른다(#113, docs/credits-reviews.md 8절). 모두 커밋하지 않는다.

부르는 곳:
- auth.service WITHDRAW_STEPS(탈퇴): delete_reports_by_user — 그 사람이 한 신고만 지우고 후기는 남긴다
- auth.service MERGE_STEPS(게스트 합치기): reassign_user — 옮길 것이 없다(게스트는 후기·신고를 못 쓴다)

후기 글과 작성자는 밖으로 내주지 않는다(결정 B, 명세 5절 「모델」). 추천·②·에이전트가 읽을 함수를 여기 열지 않는다.
"""

from sqlalchemy.orm import Session

from reviews import service


def delete_reports_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴(auth.service.WITHDRAW_STEPS)가 부른다 — 그 사람이 한 신고를 지운다. 지운 행 수. 그 사람이 쓴 후기는 남긴다
    (작성자 이름은 원래 보이지 않는다, docs/credits-reviews.md 6절 계정 수명)."""
    return service.delete_reports_by_user(db, user_id=user_id)


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(auth.service.MERGE_STEPS)가 부른다 — 옮기지 않는다. 게스트는 후기 쓰기·신고가 403이라 게스트 id로 된 행이
    없다(명세 6절). 테이블 이름 → 옮긴 행 수(늘 0). 멱등."""
    return {"reviews": 0, "review_reports": 0}

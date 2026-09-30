"""
다른 모듈이 auth를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 지금은 배치 표시이름 조회 하나뿐이다.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.models import User

WITHDRAWN_DISPLAY_NAME = "탈퇴한 구성원"


def display_names(db: Session, user_ids: Sequence[str]) -> dict[str, str]:
    """maps.for_Root.md 항목5(Member.display_name)·pins의 created_by_display_name이 쓴다.
    배치 조회 — N명 표시에 N번 쿼리하지 않는다. 탈퇴(deleted_at)한 사용자는 실명 대신
    WITHDRAWN_DISPLAY_NAME("탈퇴한 구성원")을 돌려준다 — 남는 핀·확정 항목의 작성자 표시가
    사라지지는 않되 탈퇴자의 이름은 노출하지 않는다(#155 결정, pins·maps가 이 값을 그대로 쓴다)."""
    if not user_ids:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.deleted_at).where(User.id.in_(user_ids))).all()
    return {row.id: WITHDRAWN_DISPLAY_NAME if row.deleted_at is not None else row.display_name for row in rows}

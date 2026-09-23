"""
다른 모듈이 auth를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 지금은 배치 표시이름 조회 하나뿐이다.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.models import User


def display_names(db: Session, user_ids: Sequence[str]) -> dict[str, str]:
    """maps.for_Root.md 항목5(Member.display_name)·pins의 created_by_display_name이 쓴다.
    배치 조회 — N명 표시에 N번 쿼리하지 않는다. 탈퇴(deleted_at)한 사용자도 이름은 보여준다 —
    과거 반응·핀 작성자 표시가 탈퇴 후 사라지면 안 된다(활성 여부 판정은 auth.deps의 몫이지
    이 조회가 걸러낼 이유가 없다)."""
    if not user_ids:
        return {}
    rows = db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids))).all()
    return {row.id: row.display_name for row in rows}

"""다른 모듈이 AI 코스 짜기(agent.course)에 요청하는 공개 함수(docs/architecture.md 1절). 커밋하지 않는다.

연결은 팀 결정 #580 뒤에 한다: `maps/purge.py`의 PURGE_STEPS에 `purge_map_data`, `auth/service.py`의 withdraw_user에 `delete_by_user`.
"""

from sqlalchemy.orm import Session

from agent.course import service


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 코스 run을 모두 지우고 테이블 이름 → 지운 행 수를 돌려준다.
    다른 모듈 테이블을 참조하지 않아서 PURGE_STEPS 어디에 둬도 된다."""
    return service.purge_map_data(db, map_ids=map_ids)


def delete_by_user(db: Session, *, user_id: str) -> dict[str, int]:
    """탈퇴(auth.service.withdraw_user, #155)가 부른다 — 그 사람이 요청한 코스 run(요청 한 줄, 결과)을 지운다."""
    return service.delete_by_user(db, user_id=user_id)

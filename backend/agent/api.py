"""
다른 모듈이 agent에 요청하는 공개 함수(docs/architecture.md 1절 — 다른 모듈의 데이터 변경은 그 모듈의 api.py만).
커밋하지 않는다. advise_run(추천 막힘 조언)은 M2에서 연다.

연결(maps/purge.py의 PURGE_STEPS, auth/service.py의 withdraw_user)은 #512에서 한다.
"""

from sqlalchemy.orm import Session

from agent import service


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 agent_* 7개 테이블 행을 모두 지우고 테이블 이름 → 지운
    행 수를 돌려준다. 다른 모듈 테이블을 참조하지 않아서 PURGE_STEPS 어디에 둬도 된다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)


def delete_by_user(db: Session, *, user_id: str, map_ids: list[str]) -> dict[str, int]:
    """탈퇴(auth.service.withdraw_user, #155)가 부른다 — `map_ids`에는 `maps.api.lock_member_maps`가 돌려준 지도
    목록을 넘긴다. 그 지도들의 우리 조건 요약을 지우고 agent_runs의 tool_calls·verification을 비운다. 그 사람의
    열람 기록은 지도와 무관하게 모두 지운다. 테이블 이름 → 지우거나 비운 행 수. 커밋하지 않는다.

    순서 제약은 없다(agent는 다른 모듈 테이블을 읽지 않는다). 반응 삭제 앞이든 뒤든 같은 결과다."""
    return service.delete_by_user(db, user_id=user_id, map_ids=map_ids)

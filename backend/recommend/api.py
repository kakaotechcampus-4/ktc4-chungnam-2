"""
다른 모듈이 recommend에 요청하는 공개 함수(docs/architecture.md 1절 — 다른 모듈의 데이터
변경은 그 모듈의 api.py만). 커밋하지 않는다(common/database.py get_db가 요청당 한 번 커밋).
"""

from sqlalchemy.orm import Session

from recommend import service


def delete_evidence_lines_by_author(db: Session, *, user_id: str) -> int:
    """탈퇴용 — `user_id`가 쓴 근거 줄(모든 run)을 지우고 지운 개수를 돌려준다."""
    return service.delete_evidence_lines_by_author(db, user_id=user_id)


def delete_evidence_lines_by_author_in_map(db: Session, *, user_id: str, map_id: str) -> int:
    """지도 나가기용(maps, #369) — `user_id`가 그 지도의 run에 쓴 근거 줄만 지운다. run과 후보는 남긴다."""
    return service.delete_evidence_lines_by_author_in_map(db, user_id=user_id, map_id=map_id)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 evidence_lines·candidates·regions·exclusions·
    recommend_runs만 지우고 테이블 이름 → 지운 행 수를 돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

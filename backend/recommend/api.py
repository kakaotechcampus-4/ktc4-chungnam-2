"""
다른 모듈이 recommend에 요청하는 공개 함수(docs/architecture.md 1절 — 다른 모듈의 데이터
변경은 그 모듈의 api.py만). 커밋하지 않는다(common/database.py get_db가 요청당 한 번 커밋).
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from common import categories
from recommend import constraints, core, flows, service


def delete_evidence_lines_by_author(db: Session, *, user_id: str) -> int:
    """탈퇴용 — `user_id`가 쓴 근거 줄(모든 run)을 지우고 지운 개수를 돌려준다."""
    return service.delete_evidence_lines_by_author(db, user_id=user_id)


def delete_evidence_lines_by_author_in_map(db: Session, *, user_id: str, map_id: str) -> int:
    """지도 나가기용(maps, #369) — `user_id`가 그 지도의 run에 쓴 근거 줄만 지운다. run과 후보는 남긴다."""
    return service.delete_evidence_lines_by_author_in_map(db, user_id=user_id, map_id=map_id)


def last_run_at_by_category(db: Session, *, map_id: str) -> dict[str, datetime]:
    """agent 스냅샷(docs/agent-v2.md 12.7, #522)이 부른다 — 카테고리 → 그 지도에서 가장 최근 run의 created_at.
    run이 없는 카테고리는 키가 없다. **후보, 근거, 요청자는 돌려주지 않는다** — run은 요청자만 보는 비공개 데이터라
    agent는 "그 뒤에 run이 있었나"만 본다(명세 2절 2번). 읽기 전용, 커밋하지 않는다."""
    return service.last_run_at_by_category(db, map_id=map_id)


def get_readiness(db: Session, *, map_id: str, category: str) -> dict:
    """agent의 반대 후 정체 진단(docs/agent-v2.md 6.2, 10절 get_readiness, #530)이 부른다 — 그 카테고리가 추천
    준비(⓪)를 통과했나. `{ready, answered_count, required_count}`, `GET /maps/{mapId}/recommend/readiness`의 한
    카테고리 값과 같다(같은 함수 flows.readiness_for_category). 권한은 보지 않는다(agent가 구성원 범위에서 부른다).
    추천 대상이 아닌 카테고리(숙소·기타)는 ValueError — 라우터 응답에도 그 키가 없다. 읽기 전용, 커밋하지 않는다."""
    if category not in categories.recommendable():
        raise ValueError(f"추천 대상이 아닌 카테고리: {category}")
    return flows.readiness_for_category(db, map_id=map_id, category=category)


def fact_labels() -> dict[str, str]:
    """agent 의견 갈림 분석의 축 이름(docs/agent-v2.md 6.3, #564)이 부른다 — fact_key → 근거 줄에 그리는 표시 이름
    ("quiet" → "조용한 곳"). `constraints.FACT_LABELS`의 사본이라 고쳐도 원본에 영향이 없다."""
    return dict(constraints.FACT_LABELS)


def demote_wanted_place_identity(category: str, lines: Sequence[dict]) -> list[dict]:
    """agent structure_reasons(docs/agent-v2.md 10절, #564)가 부른다 — 추천 근거 조립과 같은 #422 규칙(🚫 사유 안의
    음식 종류 "원함"은 preferred). lines는 `{fact_key, wants, badge}`(다른 키는 그대로 둔다). 원본은 바꾸지 않는다."""
    return core.demote_wanted_place_identity(lines, category)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 evidence_lines·candidates·regions·exclusions·
    recommend_runs만 지우고 테이블 이름 → 지운 행 수를 돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

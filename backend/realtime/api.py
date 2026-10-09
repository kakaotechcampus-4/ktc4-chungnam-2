"""
다른 모듈이 realtime을 부르는 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는 <module>/api.py를 통해서만").
event_log 행은 common.events.record_event로 쌓고, 지우는 쪽은 여기서 맡는다. 커밋하지 않는다.
"""

from sqlalchemy.orm import Session

from realtime import service


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 event_log만 지우고 테이블 이름 → 지운 행 수를
    돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

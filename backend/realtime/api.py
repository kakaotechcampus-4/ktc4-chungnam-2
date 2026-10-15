"""
다른 모듈이 realtime을 부르는 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는 <module>/api.py를 통해서만").
event_log 행은 common.events.record_event로 쌓고, 지우는 쪽은 여기서 맡는다. 커밋하지 않는다.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from realtime import service


def latest_seq_by_map(db: Session) -> dict[str, tuple[int, datetime]]:
    """agent claim_maps(docs/agent-v2.md 12.2, 12.5, #522, #525)가 부른다 — 지도 id → (가장 큰 event_log seq,
    그 행의 created_at). 보존 24시간 안의 행만, 전체·개인 채널 모두. 이벤트가 없는 지도는 키가 없다.
    event_log를 읽는 곳은 realtime뿐이라(docs/data-model.md common 절) 여기서 연다. type·payload·수신자는
    내보내지 않는다. 읽기 전용, 커밋하지 않는다."""
    return service.latest_seq_by_map(db)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 event_log만 지우고 테이블 이름 → 지운 행 수를
    돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

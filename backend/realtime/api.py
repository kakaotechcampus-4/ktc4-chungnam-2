"""
다른 모듈이 realtime을 부르는 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는 <module>/api.py를 통해서만").
event_log 행은 common.events.record_event로 쌓고, 지우는 쪽은 여기서 맡는다. 커밋하지 않는다.
"""

from sqlalchemy.orm import Session

from realtime import service


def visible_seqs(db: Session, *, map_id: str, after_seq: int) -> list[int]:
    """agent 커서(docs/agent-v2.md 12.5, #522)가 부른다 — 이 지도의 event_log seq 중 after_seq보다 큰 것, 오름차순.
    event_log를 읽는 곳은 realtime뿐이라(docs/data-model.md common 절) 여기서 연다. seq 번호만 돌려준다.
    seq는 모든 지도가 함께 쓰는 번호라, 한 지도의 목록에는 다른 지도 몫의 빈 번호가 섞인다. 읽기 전용, 커밋하지 않는다."""
    return service.visible_seqs(db, map_id=map_id, after_seq=after_seq)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 event_log만 지우고 테이블 이름 → 지운 행 수를
    돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

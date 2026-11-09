"""
다른 모듈이 realtime을 부르는 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는 <module>/api.py를 통해서만").
event_log 행은 common.events.record_event로 쌓고, 지우는 쪽은 여기서 맡는다. 커밋하지 않는다.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from realtime import service
from realtime.dispatcher import dispatcher


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


def purge_old_events(db: Session, *, now: datetime) -> int:
    """maintenance가 부른다(#1016) — 재전송 창(`service.RETENTION`)을 지난 event_log 행을 지운다. 지우는 기준
    (`service.PURGE_AFTER_HOURS`)과 한 번에 지우는 양(`service.PURGE_BATCH`)은 realtime이 정한다(#1474). 남았으면 다음 실행이
    이어서 지운다. 지울 게 없으면 0. 커밋하지 않는다."""
    return service.purge_old_events(db, now=now)


def online_user_ids(map_id: str) -> set[str]:
    """maps가 구성원 목록의 `online`을 채울 때 부른다(#1551) — 이 지도의 전체 채널 SSE에 연결이 하나라도 열려
    있거나, 마지막 연결이 끊긴 지 `presence.GRACE`(30초)가 안 된 구성원의 user_id. 같은 사람의 탭·기기 여럿은
    한 명이다. 이 프로세스의 메모리 기준이라 서버가 여러 개면 자기 연결만 본다(docs/events.md 「접속 상태의 한계」).
    저장하지 않고 DB를 읽지 않는다. 구성원인지는 부르는 쪽이 거른다."""
    return dispatcher.presence.online_user_ids(map_id)

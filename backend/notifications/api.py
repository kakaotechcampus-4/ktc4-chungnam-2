"""
다른 모듈이 notifications를 부르는 유일한 접점(docs/architecture.md 1절 — 다른 모듈의 데이터 변경은 그 모듈의
api.py만). 사용법은 notifications/for_Root.md. 모두 호출한 쪽 트랜잭션에 참여하고 커밋하지 않는다.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from notifications import core, service
from notifications.service import RETENTION_DAYS

__all__ = ["RETENTION_DAYS", "compose_message", "delete_by_user", "notify", "purge_old"]


def compose_message(type: str, *, actor_name: str | None = None, map_title: str | None = None,
                    reaction: str | None = None) -> str:
    """종류별 알림 문장. `notify`의 `message`는 이 함수로 만든다 — 문장 틀에 반대 사유 원문·핀 메모를 넣을
    자리가 없어서 그것들이 알림함으로 새지 않는다. 모르는 종류면 ValueError."""
    return core.compose_message(type, actor_name=actor_name, map_title=map_title, reaction=reaction)


def notify(db: Session, *, user_id: str, type: str, map_id: str, map_title: str | None, message: str,
           pin_id: str | None = None, actor_id: str | None = None) -> UUID | None:
    """`user_id`(수신자) 한 명의 알림함에 알림을 쓴다. 이벤트를 쓰는 같은 트랜잭션에서 부른다 — 호출한 쪽
    트랜잭션에 참여하고 commit은 호출자가 한다. 수신자가 여럿이면 수신자마다 한 번씩 부른다.

    notify 안에서 거른다(호출자가 따로 거를 필요 없다): `actor_id`가 수신자와 같으면(행위자 본인) 만들지 않고,
    수신자가 그 종류를 꺼 뒀으면(notification_prefs) 만들지 않는다. 만들었으면 알림 id, 걸렀으면 None.
    모르는 `type`이면 ValueError — 종류 목록은 api-spec NotificationType이다."""
    return service.notify(
        db, user_id=user_id, type=type, map_id=map_id, map_title=map_title, message=message,
        pin_id=pin_id, actor_id=actor_id,
    )


def delete_by_user(db: Session, *, user_id: str) -> dict[str, int]:
    """탈퇴(auth.service.withdraw_user, #155)가 부른다 — 그 사용자의 알림과 알림 설정을 모두 지운다. 테이블 이름 →
    지운 행 수. 다른 모듈 테이블을 읽지 않아서 순서 제약이 없다."""
    return service.delete_by_user(db, user_id=user_id)


def purge_old(db: Session, *, now: datetime, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    """정리 작업(#168)이 부른다 — `now`보다 `older_than_days`(기본 90)일 넘게 지난 알림을 지운다. 지도 정리(#431)와
    달리 map_id를 보지 않는다(삭제된 지도의 `map_deleted` 알림이 남은 구성원에게 보여야 한다). 테이블 이름 → 지운 행 수.
    호출 연결은 아직 없다(#168 이슈에 남겼다)."""
    return service.purge_old(db, now=now, older_than_days=older_than_days)

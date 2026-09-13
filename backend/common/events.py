"""상태 변경과 같은 트랜잭션에 이벤트 행을 남긴다. 여기서 전송은 하지 않는다 —
전송은 realtime이 커밋된 event_log를 읽어서 한다(docs/events.md 「전달 보장」)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from common.database import Base

Channel = Literal["public", "private"]


@dataclass(frozen=True)
class Event:
    """core.py(순수 함수)가 만들어 반환하는 값. I/O를 모른다.

    channel과 recipient_user_id의 일관성은 DB CheckConstraint(ck_event_log_private_recipient)
    가 최종 방어선이지만, 그건 커밋 시점에야 IntegrityError(500)로 터진다 — 여기서 생성 시점에
    바로 잡아서 호출한 모듈이 명확한 원인을 보게 한다(DeepSeek 검수 지적: public+recipient
    조합이 500으로 늦게 터지는 문제)."""
    map_id: str
    channel: Channel
    type: str                              # docs/events.md 11종 중 하나
    payload: dict
    recipient_user_id: str | None = None   # channel="private"일 때만 채운다

    def __post_init__(self) -> None:
        # channel 값 자체도 검사한다(Antigravity 검수 지적) — "private"/"public" 둘 다 아니고
        # recipient_user_id도 None이면 아래 일관성 검사를 그냥 통과해버려서 잘못된 channel
        # 문자열이 DB의 Enum 제약 위반(늦은 IntegrityError)까지 그대로 흘러간다.
        if self.channel not in get_args(Channel):
            raise ValueError(f"channel={self.channel!r} — 'public' 또는 'private'만 쓴다")
        if (self.channel == "private") != (self.recipient_user_id is not None):
            raise ValueError(
                f"channel={self.channel!r}인데 recipient_user_id={self.recipient_user_id!r} — "
                "private은 반드시 recipient_user_id를 채우고, public은 절대 채우지 않는다."
            )


class EventLog(Base):
    __tablename__ = "event_log"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(Enum("public", "private", name="event_channel"), nullable=False)
    recipient_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # PostgreSQL의 now()는 트랜잭션 시작 시각이다(문 실행 시각이 아님) — 같은 트랜잭션에서 여러
    # 이벤트를 기록하면 created_at이 전부 같은 값이 된다(2차 DeepSeek 재검수가 문서화 누락을
    # 지적). 정렬·순서 판단은 반드시 seq를 쓴다 — created_at은 보존기간 삭제(§index)용일 뿐,
    # 순서 보장 용도가 아니다.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("ix_event_log_map_seq", "map_id", "seq"),
        Index("ix_event_log_created_at", "created_at"),        # 보존기간 삭제용
        CheckConstraint("(channel = 'private') = (recipient_user_id IS NOT NULL)",
                        name="ck_event_log_private_recipient"),
    )


def record_event(db: Session, event: "Event | None") -> None:
    """호출자의 세션에 그대로 붙인다 — 커밋은 하지 않는다(common/database.py get_db가 유일한 커밋 지점).
    event=None이면 아무 것도 하지 않는다(비공개 핀은 전체 채널에 발행하지 않는다, 가드레일 1)."""
    if event is None:
        return
    db.add(EventLog(map_id=event.map_id, channel=event.channel, type=event.type,
                    payload=event.payload, recipient_user_id=event.recipient_user_id))

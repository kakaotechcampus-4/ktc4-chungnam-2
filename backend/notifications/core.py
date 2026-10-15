"""
순수 함수 — DB·시계 없이 입력만으로 결과가 정해지는 것(docs/code-quality.md 기능형 코어).
알림 종류·문장 틀, 커서, 설정 합치기, 문자열 자르기.
"""

import base64
import binascii
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime

# api-spec NotificationType의 선언 순서 — GET /me/notification-prefs가 이 순서로 돌려준다
TYPES: tuple[str, ...] = ("pin_reaction", "member_joined", "owner_changed", "map_deleted", "my_ai_pin_published")

MESSAGE_MAX = 200     # api-spec Notification.message maxLength
MAP_TITLE_MAX = 100   # api-spec Notification.map_title maxLength

DEFAULT_ACTOR = "구성원"

# 문장은 서버가 만든다. 반대 사유 원문·핀 메모를 받는 자리를 일부러 두지 않는다 — 문장 틀에 넣을 수 있는 값은
# 행위자 이름·지도 제목·반응 종류뿐이다.
_REACTION_PHRASES = {"like": "♥를", "dislike": "🚫 반대를"}


def compose_message(type: str, *, actor_name: str | None = None, map_title: str | None = None,
                    reaction: str | None = None) -> str:
    """알림 문장. `reaction`은 pin_reaction에서만 쓰며 "like"·"dislike" 외의 값은 일반 문장으로 돌린다."""
    actor = (actor_name or "").strip() or DEFAULT_ACTOR
    if type == "pin_reaction":
        phrase = _REACTION_PHRASES.get(reaction or "", "반응을")
        text = f"{actor}님이 내 핀에 {phrase} 남겼어요"
    elif type == "member_joined":
        text = f"{actor}님이 지도에 들어왔어요"
    elif type == "owner_changed":
        text = "내가 이 지도의 방장이 되었어요"
    elif type == "map_deleted":
        title = (map_title or "").strip()
        text = f"'{clip(title, 40)}' 지도가 삭제되었어요" if title else "지도가 삭제되었어요"
    elif type == "my_ai_pin_published":
        text = f"{actor}님이 내가 요청한 AI 추천을 지도에 올렸어요"
    else:
        raise ValueError(f"모르는 알림 종류: {type!r}")
    return clip(text, MESSAGE_MAX)


def clip(text: str, limit: int) -> str:
    """limit자를 넘으면 자르고 …를 붙인다(결과도 limit자 이하)."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    """`before` 값 — 클라이언트에는 뜻 없는 문자열이다. URL에 그대로 실어도 되도록 base64url로 만든다."""
    raw = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """encode_cursor의 역. 형식이 틀리면 ValueError."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        iso, _, raw_id = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        created_at = datetime.fromisoformat(iso)
        if created_at.tzinfo is None:
            raise ValueError("시각에 시간대가 없다")
        return created_at, uuid.UUID(raw_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"잘못된 before 커서: {cursor!r}") from exc


def parse_ids(ids: Iterable[str]) -> list[uuid.UUID]:
    """읽음 처리 요청의 id 중 알림 id 형식인 것만. 형식이 아닌 값은 "없는 id"와 같이 조용히 버린다."""
    parsed: list[uuid.UUID] = []
    for raw in ids:
        try:
            parsed.append(uuid.UUID(raw))
        except ValueError:
            continue
    return parsed


def effective_prefs(stored: dict[str, bool]) -> list[tuple[str, bool]]:
    """저장된 설정에 기본값(켜짐)을 채워 모든 종류를 선언 순서로."""
    return [(t, stored.get(t, True)) for t in TYPES]


def last_wins(updates: Sequence[tuple[str, bool]]) -> dict[str, bool]:
    """같은 종류가 여러 번 오면 뒤의 것."""
    return dict(updates)


def is_known_type(type: str) -> bool:
    return type in TYPES

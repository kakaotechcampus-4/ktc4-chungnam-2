"""목록 「더 보기」 커서 한 곳(#973). 알림함(notifications)과 장소 후기(reviews)가 쓴다.

커서는 마지막으로 보인 행의 `created_at|id`를 base64url로 만든 문자열이다. 화면에는 뜻 없는 문자열이고 URL에 그대로 실을 수 있다.
잘못된 값은 ValueError만 낸다. 422로 바꾸는 일과 그 문구는 부르는 모듈 서비스가 한다(쿼리 이름이 모듈마다 다르다).
다음에 목록 페이지를 만드는 기능도 이것을 쓴다.
"""

import base64
import binascii
import uuid
from datetime import datetime


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """마지막으로 보인 행의 커서. '+'·'='가 없어 쿼리 문자열에 그대로 실을 수 있다."""
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """encode_cursor의 역. 형식이 틀리거나 시각에 시간대가 없으면 ValueError — 메시지에 받은 값(사용자 입력)을 싣지 않는다."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        iso, _, raw_id = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        created_at = datetime.fromisoformat(iso)
        if created_at.tzinfo is None:
            raise ValueError("시각에 시간대가 없다")
        return created_at, uuid.UUID(raw_id)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ValueError("잘못된 목록 커서") from None

"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시계(datetime.now())·secrets 모듈을
쓰지 않는다 — 둘 다 비결정적이라 service.py가 만들어 파라미터로 넘긴다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from common.errors import AppError
from common.events import Event
from maps.schemas import Map, Member

# 목서버(contracts/mocks/handlers/maps.ts:33)와 동일한 7일 — 정본이 없다(maps/for_Root.md 보고).
INVITE_TTL = timedelta(days=7)


@dataclass(frozen=True)
class NewMap:
    """검증·정규화를 마친 지도 생성 입력."""

    title: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class MapRecord:
    """ORM 행에서 응답 조립에 필요한 값만 추린 것 — core가 SQLAlchemy를 몰라도 되게 한다
    (pins/core.py::PinRecord와 동일한 패턴)."""

    id: str
    title: str
    start_date: date
    end_date: date


def validate_map_create(title: str, start_date: date, end_date: date) -> NewMap:
    """공백만 있는 제목은 없는 것과 같다 취급(pins/core.py의 반응 사유 검증과 같은 원칙).
    end_date는 start_date와 같은 날도 허용한다(당일치기) — CHECK 제약과 동일한 `>=`."""
    normalized_title = title.strip()
    if not normalized_title:
        raise AppError("VALIDATION_ERROR", "제목이 비어 있습니다")
    if end_date < start_date:
        raise AppError("VALIDATION_ERROR", "end_date는 start_date 이후여야 합니다")
    return NewMap(title=normalized_title, start_date=start_date, end_date=end_date)


def invite_expires_at(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다 — naive datetime은 KST/UTC 혼동을 부른다")
    return now + INVITE_TTL


def check_invite_acceptable(expires_at: datetime, now: datetime) -> None:
    """만료된 초대는 401(계약이 그 엔드포인트에 선언한 유일한 에러) — 존재하지 않는 토큰과
    구분되지 않는 응답이어야 한다(토큰 존재 여부를 탐지당하지 않는다), 호출부가 같은 코드를 쓴다."""
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("expires_at·now는 모두 timezone-aware여야 합니다")
    if now >= expires_at:
        raise AppError("UNAUTHORIZED", "초대 링크가 유효하지 않거나 만료되었습니다")


def build_invite_url(base_url: str, token: str) -> str:
    """base_url 끝의 '/' 유무와 무관하게 '//invites/'가 생기지 않게 한다."""
    return f"{base_url.rstrip('/')}/invites/{token}"


def to_map_response(record: MapRecord, *, member_count: int, confirmed_count: int | None) -> Map:
    """confirmed_count는 shortlist_items 개수 — shortlist.api.count_confirmed로 채운다(루트,
    maps/for_Root.md 항목 5 해결). 그래도 매개변수를 Optional로 남긴다 — 값을 못 구하는
    호출부가 생기면 0(거짓 "확정 0개")이 아니라 None(라우터가 키 자체를 생략)으로 정직하게
    빠지게 하려는 의도다."""
    return Map(
        id=record.id,
        title=record.title,
        start_date=record.start_date,
        end_date=record.end_date,
        member_count=member_count,
        confirmed_count=confirmed_count,
    )


def to_member_response(user_id: str, *, display_name: str | None, online: bool | None) -> Member:
    """display_name은 auth.api.display_names로 채운다(루트, maps/for_Root.md 항목 5 해결).
    online은 여전히 채울 데이터 출처가 없다(realtime에 presence 없음, #32 별건) — user_id로
    대체하거나 False로 채우지 않는다(그럴싸해 보이는 거짓 fallback이다)."""
    return Member(user_id=user_id, display_name=display_name, online=online)


def member_joined_event(map_id: str, member: Member) -> Event:
    """docs/events.md member.joined — public 채널, 페이로드는 Member(생략된 필드 제외)."""
    return Event(
        map_id=map_id,
        channel="public",
        type="member.joined",
        payload=member.model_dump(exclude_none=True),
    )

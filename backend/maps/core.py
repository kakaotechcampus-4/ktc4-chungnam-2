"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시계(datetime.now())·secrets 모듈을
쓰지 않는다 — 둘 다 비결정적이라 service.py가 만들어 파라미터로 넘긴다.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from authz.core import Principal, Resource, can
from authz.policy import Role
from authz.schemas import Permissions
from common.errors import AppError
from common.events import Event
from maps.schemas import InviteSummary, Map, MapRegion, Member, NextOwner

WITHDRAWN_MEMBER_NAME = "탈퇴한 구성원"

# 내 지도 상한(#369 15번) — 만들거나 참여한 지도 합산, 삭제된 지도와 나간 지도는 세지 않는다.
MAP_LIMIT = 10

# 목서버(contracts/mocks/handlers/maps.ts:33)와 동일한 7일 — 정본이 없다(maps/for_Root.md 보고).
INVITE_TTL = timedelta(days=7)


@dataclass(frozen=True)
class NewMap:
    """검증·정규화를 마친 지도 생성 입력. region은 선택 — 없으면 지금처럼 첫 핀 좌표로
    지역을 정한다(#22)."""

    title: str
    start_date: date
    end_date: date
    region: MapRegion | None = None


@dataclass(frozen=True)
class MapRecord:
    """ORM 행에서 응답 조립에 필요한 값만 추린 것 — core가 SQLAlchemy를 몰라도 되게 한다
    (pins/core.py::PinRecord와 동일한 패턴). region_label·region_lat·region_lng은 셋 다 있거나
    셋 다 None이다 — DB의 CHECK(region_label IS NULL) = (region_center IS NULL)과 짝을 맞춘다."""

    id: str
    title: str
    start_date: date
    end_date: date
    created_by: str
    region_label: str | None = None
    region_lat: float | None = None
    region_lng: float | None = None


@dataclass(frozen=True)
class MembershipEntry:
    """memberships 행에서 위임 판정에 필요한 값만 추린 것. id는 joined_at이 같을 때의 순서용(#369 8번)."""

    id: uuid.UUID
    user_id: str
    role: Role
    joined_at: datetime


def validate_map_create(
    title: str, start_date: date, end_date: date, region: MapRegion | None = None
) -> NewMap:
    """공백만 있는 제목은 없는 것과 같다 취급(pins/core.py의 반응 사유 검증과 같은 원칙).
    end_date는 start_date와 같은 날도 허용한다(당일치기) — CHECK 제약과 동일한 `>=`.
    region이 왔으면 label 공백 여부·lat/lng 범위를 pins/core.py::validate_create의 좌표
    검증과 같은 기준으로 검사한다(가드레일과 무관한 단순 입력 검증)."""
    normalized_title = title.strip()
    if not normalized_title:
        raise AppError("VALIDATION_ERROR", "제목이 비어 있습니다")
    if end_date < start_date:
        raise AppError("VALIDATION_ERROR", "end_date는 start_date와 같거나 그 이후여야 합니다")

    normalized_region = None
    if region is not None:
        normalized_label = region.label.strip()
        if not normalized_label:
            raise AppError("VALIDATION_ERROR", "region.label이 비어 있습니다")
        if not (-90 <= region.lat <= 90):
            raise AppError("VALIDATION_ERROR", "region.lat은 -90~90 범위여야 합니다")
        if not (-180 <= region.lng <= 180):
            raise AppError("VALIDATION_ERROR", "region.lng는 -180~180 범위여야 합니다")
        normalized_region = MapRegion(label=normalized_label, lat=region.lat, lng=region.lng)

    return NewMap(
        title=normalized_title, start_date=start_date, end_date=end_date, region=normalized_region
    )


def check_map_limit(my_map_count: int) -> None:
    """지도를 만들거나 새로 참여하기 전에 부른다. 이미 MAP_LIMIT개면 409 MAP_LIMIT(detail: limit, count)."""
    if my_map_count >= MAP_LIMIT:
        raise AppError("MAP_LIMIT", detail={"limit": MAP_LIMIT, "count": my_map_count})


def invite_expires_at(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다 — naive datetime은 KST/UTC 혼동을 부른다")
    return now + INVITE_TTL


def check_invite_acceptable(expires_at: datetime, now: datetime) -> None:
    """만료된 초대는 410 INVITE_EXPIRED(#159, 없는 토큰의 404 INVITE_NOT_FOUND와 구분한다 —
    수락 화면이 "새 링크를 요청하세요"를 안내해야 해서 계약이 둘을 나눴다). 조회(GET)와
    수락(POST)이 같은 판정을 쓴다."""
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("expires_at·now는 모두 timezone-aware여야 합니다")
    if now >= expires_at:
        raise AppError("INVITE_EXPIRED")


def to_invite_summary(
    record: MapRecord,
    *,
    member_count: int,
    pin_count: int,
    inviter_display_name: str | None,
    expires_at: datetime,
) -> InviteSummary:
    """map_id와 핀 등 지도 내용은 싣지 않는다 — 토큰 소지자가 가입 전에 볼 수 있는 최소한만.
    초대자 이름을 못 구하면(users 행이 없음) '탈퇴한 구성원'으로 채운다(스펙 InviteSummary)."""
    return InviteSummary(
        title=record.title,
        start_date=record.start_date,
        end_date=record.end_date,
        member_count=member_count,
        pin_count=pin_count,
        inviter_display_name=inviter_display_name or WITHDRAWN_MEMBER_NAME,
        expires_at=expires_at,
    )


def build_invite_url(base_url: str, token: str) -> str:
    """base_url 끝의 '/' 유무와 무관하게 '//invites/'가 생기지 않게 한다."""
    return f"{base_url.rstrip('/')}/invites/{token}"


def pick_successor(
    memberships: Iterable[MembershipEntry], withdrawn: set[str], leaving_user_id: str
) -> str | None:
    """방장이 빠질 때 방장이 될 사람(#369 확정 3번, 구현 결정 8번). 나가는 사람과 탈퇴자를 빼고
    joined_at이 가장 빠른 구성원, 같으면 memberships.id 순. 넘길 사람이 없으면 None."""
    candidates = [
        m for m in memberships if m.user_id != leaving_user_id and m.user_id not in withdrawn
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: (m.joined_at, m.id)).user_id


def role_in(roster: Iterable[MembershipEntry], user_id: str) -> Role | None:
    return next((m.role for m in roster if m.user_id == user_id), None)


def owner_successor(
    principal: Principal, roster: Iterable[MembershipEntry], withdrawn: set[str]
) -> str | None:
    """요청자가 방장일 때만 후임을 계산한다 — 구성원이 나갈 때는 위임이 없다."""
    if principal.role != "owner":
        return None
    return pick_successor(roster, withdrawn, principal.user_id)


def can_leave(role: Role | None, successor: str | None) -> bool:
    """구성원은 언제나 나갈 수 있다. 방장은 넘길 사람이 있을 때만(#369 9번)."""
    if role is None:
        return False
    return role != "owner" or successor is not None


def check_leave_allowed(role: Role, successor: str | None) -> None:
    if not can_leave(role, successor):
        raise AppError("OWNER_CANNOT_LEAVE")


def map_permissions(principal: Principal, successor: str | None) -> Permissions:
    """Map 응답의 permissions(#369). 역할로 정해지는 부분은 authz.can이, 넘길 사람이 있는지는 지도
    상태라 can_leave가 판정한다(docs/permissions.md map.leave 주석)."""
    resource = Resource(type="map", map_id=principal.map_id)
    return Permissions(
        can_delete=can(principal, "map.delete", resource),
        can_leave=can(principal, "map.leave", resource) and can_leave(principal.role, successor),
    )


def to_next_owner(principal: Principal, successor: str | None, display_name: str | None) -> NextOwner | None:
    """요청자가 방장이고 넘길 사람이 있을 때만 채운다. 이름을 못 구하면(users 행이 없음) 거짓 이름을
    만들지 않고 생략한다."""
    if principal.role != "owner" or successor is None or display_name is None:
        return None
    return NextOwner(user_id=successor, display_name=display_name)


def to_map_response(
    record: MapRecord,
    *,
    member_count: int,
    pin_count: int,
    confirmed_count: int | None,
    permissions: Permissions,
    my_role: Role | None,
    viewer_id: str,
    next_owner: NextOwner | None = None,
) -> Map:
    """confirmed_count는 shortlist_items 개수 — shortlist.api.count_confirmed로 채운다(루트,
    maps/for_Root.md 항목 5 해결). 그래도 매개변수를 Optional로 남긴다 — 값을 못 구하는
    호출부가 생기면 0(거짓 "확정 0개")이 아니라 None(라우터가 키 자체를 생략)으로 정직하게
    빠지게 하려는 의도다.

    region은 record.region_label이 있을 때만 조립한다 — DB의 CHECK 제약과 같은 "셋 다 있거나
    셋 다 없거나" 전제를 core에서도 지킨다."""
    region = None
    if record.region_label is not None:
        region = MapRegion(label=record.region_label, lat=record.region_lat, lng=record.region_lng)
    return Map(
        id=record.id,
        title=record.title,
        start_date=record.start_date,
        end_date=record.end_date,
        region=region,
        member_count=member_count,
        pin_count=pin_count,
        confirmed_count=confirmed_count,
        permissions=permissions,
        my_role=my_role,
        created_by_me=record.created_by == viewer_id,
        next_owner=next_owner,
    )


def to_member_response(
    user_id: str, *, role: Role, display_name: str | None, online: bool | None
) -> Member:
    """role은 memberships.role 그대로다(#369 11번 — maps.created_by로 판정하지 않는다).
    display_name은 auth.api.display_names로 채운다(루트, maps/for_Root.md 항목 5 해결).
    online은 여전히 채울 데이터 출처가 없다(realtime에 presence 없음, #32 별건) — user_id로
    대체하거나 False로 채우지 않는다(그럴싸해 보이는 거짓 fallback이다)."""
    return Member(user_id=user_id, role=role, display_name=display_name, online=online)


def member_joined_event(map_id: str, member: Member) -> Event:
    """docs/events.md member.joined — public 채널, 페이로드는 Member(생략된 필드 제외)."""
    return Event(
        map_id=map_id,
        channel="public",
        type="member.joined",
        payload=member.model_dump(exclude_none=True),
    )


def map_deleted_event(map_id: str) -> Event:
    """docs/events.md map.deleted — public 채널. 삭제와 같은 트랜잭션에 기록한다(#369)."""
    return Event(map_id=map_id, channel="public", type="map.deleted", payload={"map_id": map_id})


def member_left_event(map_id: str, user_id: str, new_owner_user_id: str | None) -> Event:
    """docs/events.md member.left — public 채널(#369). 위임이 없었으면 new_owner_user_id는 null."""
    return Event(
        map_id=map_id,
        channel="public",
        type="member.left",
        payload={"map_id": map_id, "user_id": user_id, "new_owner_user_id": new_owner_user_id},
    )

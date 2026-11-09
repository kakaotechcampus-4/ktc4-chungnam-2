"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시계(datetime.now())·secrets 모듈을
쓰지 않는다 — 둘 다 비결정적이라 service.py가 만들어 파라미터로 넘긴다.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from auth.api import WITHDRAWN_DISPLAY_NAME   # 탈퇴한 사람 표시 이름은 auth 한 곳(#1475)
from authz.core import Principal, Resource, can
from authz.policy import Role
from authz.schemas import Permissions
from common.errors import AppError
from common.events import Event
from maps.schemas import (
    TITLE_MAX_LENGTH, Invite, InviteSummary, Map, MapNews, MapRegion, Member, NewReaction, NextOwner, TrashedMap,
)

# 내 지도 상한(#369 15번) — 만들거나 참여한 지도 합산, 삭제된 지도와 나간 지도는 세지 않는다.
MAP_LIMIT = 20

# 여행 기간 상한 일수(#1371) — 시작일·종료일을 포함한다. 422 TRIP_TOO_LONG의 detail.limit과 GET /maps의 trip_max_days가 같은 값이다.
TRIP_MAX_DAYS = 90

# 삭제한 지도를 복구할 수 있는 기간(#464). 정리 작업이 지우는 기준과 같은 값이다 — 여기 한 곳에서 정한다.
# 정리 API(api.purge_deleted_maps)는 기간을 받지 않고 이 값을 쓴다(#1474). 응답의 retention_days도 이 값이다.
TRASH_RETENTION = timedelta(days=30)

# 초대 링크 유효 기간 7일. 정본은 docs/data-model.md invites 절(목서버 contracts/mocks/handlers/maps.ts와 같다).
INVITE_TTL = timedelta(days=7)

# 지도 대표 이미지(#1445) — 받는 형식과 크기 상한. 422 COVER_INVALID의 detail로 내려 화면이 숫자를 적지 않게 한다.
# 브라우저가 1200px 이하 WebP로 줄여 올리는 크기에 여유를 둔 값이다. 형식은 앞 바이트로도 확인한다(이름표만 바꾼 파일을 막는다).
COVER_MAX_BYTES = 512 * 1024
_COVER_MAGIC = {
    "image/webp": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    "image/jpeg": lambda data: data[:3] == b"\xff\xd8\xff",
    "image/png": lambda data: data[:8] == b"\x89PNG\r\n\x1a\n",
}
COVER_TYPES = tuple(_COVER_MAGIC)


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
    color: str | None = None


@dataclass(frozen=True)
class MembershipEntry:
    """memberships 행에서 위임 판정에 필요한 값만 추린 것. id는 joined_at이 같을 때의 순서용(#369 8번)."""

    id: uuid.UUID
    user_id: str
    role: Role
    joined_at: datetime


@dataclass(frozen=True)
class InviteRecord:
    """invites 행에서 목록·재사용 판정에 필요한 값만 추린 것(#467)."""

    token: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    used_count: int


def validate_map_create(
    title: str, start_date: date, end_date: date, region: MapRegion | None = None, *, check_trip_length: bool = True
) -> NewMap:
    """공백만 있는 제목은 없는 것과 같다 취급(pins/core.py의 반응 사유 검증과 같은 원칙).
    end_date는 start_date와 같은 날도 허용한다(당일치기) — CHECK 제약과 동일한 `>=`.
    region이 왔으면 label 공백 여부·lat/lng 범위를 pins/core.py::validate_create의 좌표
    검증과 같은 기준으로 검사한다(가드레일과 무관한 단순 입력 검증).
    기간이 TRIP_MAX_DAYS를 넘으면 422 TRIP_TOO_LONG(#1371). check_trip_length=False는 날짜를 바꾸지 않는 수정용이다."""
    normalized_title = title.strip()
    if not normalized_title:
        raise AppError("VALIDATION_ERROR", "제목을 입력해 주세요")
    if end_date < start_date:
        raise AppError("VALIDATION_ERROR", "끝나는 날은 시작하는 날과 같거나 그 뒤여야 해요")
    if check_trip_length and (end_date - start_date).days + 1 > TRIP_MAX_DAYS:
        raise AppError("TRIP_TOO_LONG", detail={"limit": TRIP_MAX_DAYS})

    normalized_region = None
    if region is not None:
        normalized_label = region.label.strip()
        if not normalized_label:
            raise AppError("VALIDATION_ERROR", "지역 이름을 입력해 주세요")
        if not (-90 <= region.lat <= 90):
            raise AppError("VALIDATION_ERROR", "지역 위도는 -90~90 사이여야 해요")
        if not (-180 <= region.lng <= 180):
            raise AppError("VALIDATION_ERROR", "지역 경도는 -180~180 사이여야 해요")
        normalized_region = MapRegion(label=normalized_label, lat=region.lat, lng=region.lng)

    return NewMap(
        title=normalized_title, start_date=start_date, end_date=end_date, region=normalized_region
    )


def validate_map_update(
    current: MapRecord,
    *,
    title: str | None,
    start_date: date | None,
    end_date: date | None,
    region: MapRegion | None,
) -> NewMap:
    """PATCH(#465) — 보낸 필드(None이 아닌 것)를 기존 값에 합친 결과를 생성과 같은 규칙으로 검사한다.
    종료일만 보내도 기존 시작일과 비교한다. 기간 상한(#1371)은 시작일이나 종료일을 보낸 요청에서만 본다 — 이미 상한을
    넘은 지도의 제목만 고치는 요청은 막지 않는다. region은 바꾸기만 된다 — 안 보내면 기존 값을 그대로 둔다."""
    current_region = None
    if current.region_label is not None:
        current_region = MapRegion(label=current.region_label, lat=current.region_lat, lng=current.region_lng)
    return validate_map_create(
        current.title if title is None else title,
        current.start_date if start_date is None else start_date,
        current.end_date if end_date is None else end_date,
        current_region if region is None else region,
        check_trip_length=start_date is not None or end_date is not None,
    )


def check_map_limit(my_map_count: int) -> None:
    """지도를 만들거나 새로 참여하기 전에 부른다. 이미 MAP_LIMIT개면 409 MAP_LIMIT(detail: limit, count)."""
    if my_map_count >= MAP_LIMIT:
        raise AppError("MAP_LIMIT", detail={"limit": MAP_LIMIT, "count": my_map_count})


def invite_expires_at(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다 — naive datetime은 KST/UTC 혼동을 부른다")
    return now + INVITE_TTL


def check_invite_acceptable(
    expires_at: datetime, now: datetime, revoked_at: datetime | None = None
) -> None:
    """방장이 끈 초대는 410 INVITE_REVOKED(#467), 만료된 초대는 410 INVITE_EXPIRED(#159, 없는 토큰의
    404 INVITE_NOT_FOUND와 구분한다 — 수락 화면이 "새 링크를 요청하세요"를 안내해야 해서 계약이 둘을
    나눴다). 끈 링크가 만료까지 지났어도 끈 쪽이 먼저다 — 방장의 의사가 더 구체적인 사유다. 조회(GET)와
    수락(POST)이 같은 판정을 쓴다."""
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("expires_at·now는 모두 timezone-aware여야 합니다")
    if revoked_at is not None:
        raise AppError("INVITE_REVOKED")
    if now >= expires_at:
        raise AppError("INVITE_EXPIRED")


def is_invite_live(invite: InviteRecord, now: datetime) -> bool:
    """끄지 않았고 만료 전이다 — 목록과 재사용이 같은 기준을 쓴다."""
    return invite.revoked_at is None and now < invite.expires_at


def live_invites_newest_first(invites: Iterable[InviteRecord], now: datetime) -> list[InviteRecord]:
    """GET /maps/{mapId}/invites(#467) — 유효한 링크만, 만든 시각 최신순. 같은 시각이면 토큰 순(결정적)."""
    return sorted(
        (i for i in invites if is_invite_live(i, now)), key=lambda i: (i.created_at, i.token), reverse=True
    )


def pick_reusable_invite(
    invites: Iterable[InviteRecord], user_id: str, now: datetime
) -> InviteRecord | None:
    """POST /maps/{mapId}/invite(#467) — 내가 만든 유효한 링크 중 가장 최근 것. 남이 만든 링크는 재사용하지
    않는다(끄는 권한과 "누가 만든 링크인지" 표시가 어긋난다). 없으면 None — 호출부가 새로 만든다."""
    live = live_invites_newest_first((i for i in invites if i.created_by == user_id), now)
    return live[0] if live else None


def check_invite_revocable(principal: Principal) -> None:
    """DELETE /invites/{token}(#467) — 토큰만으론 지도를 알 수 없어 라우터 가드를 못 쓴다. 그 지도의 구성원이
    아니면 토큰의 존재를 흘리지 않도록 없는 토큰(404)과 같게, 구성원인데 방장이 아니면 403이다."""
    if principal.role is None:
        raise AppError("INVITE_NOT_FOUND")
    if not can(principal, "invite.revoke", Resource(type="map", map_id=principal.map_id)):
        raise AppError("FORBIDDEN")


def to_invite(
    invite: InviteRecord, *, url: str, created_by_display_name: str | None = None, detailed: bool = False
) -> Invite:
    """발급 응답은 token·url·expires_at만, 목록(detailed)은 만든 시각·만든 사람·사용 횟수까지 싣는다.
    만든 사람 이름을 못 구하면(users 행이 없음) '탈퇴한 구성원'(스펙 Invite)."""
    if not detailed:
        return Invite(token=invite.token, url=url, expires_at=invite.expires_at)
    return Invite(
        token=invite.token, url=url, expires_at=invite.expires_at, created_at=invite.created_at,
        created_by_display_name=created_by_display_name or WITHDRAWN_DISPLAY_NAME,
        used_count=invite.used_count,
    )


def to_invite_summary(
    record: MapRecord,
    *,
    member_count: int,
    pin_count: int,
    inviter_display_name: str | None,
    expires_at: datetime,
    already_member: bool = False,
) -> InviteSummary:
    """map_id와 핀 등 지도 내용은 싣지 않는다 — 토큰 소지자가 가입 전에 볼 수 있는 최소한만.
    초대자 이름을 못 구하면(users 행이 없음) '탈퇴한 구성원'으로 채운다(스펙 InviteSummary)."""
    return InviteSummary(
        title=record.title,
        start_date=record.start_date,
        end_date=record.end_date,
        member_count=member_count,
        pin_count=pin_count,
        inviter_display_name=inviter_display_name or WITHDRAWN_DISPLAY_NAME,
        expires_at=expires_at,
        already_member_map_id=record.id if already_member else None,
    )


def build_invite_url(base_url: str, token: str) -> str:
    """base_url 끝의 '/' 유무와 무관하게 '//invites/'가 생기지 않게 한다."""
    return f"{base_url.rstrip('/')}/invites/{token}"


_COPY_SUFFIX = re.compile(r" \((\d+)\)$")


def copy_title(source_title: str, taken: set[str]) -> str:
    """지도 복사본 제목(#1446) — 「원래 제목 (n)」. 원래 제목 끝의 「 (k)」는 떼고 붙인다(복사본을 또 복사해도 「(1) (1)」이 되지 않게).
    n은 1부터 taken(복사하는 사람의 지도 제목)에 없는 가장 작은 수. 제목 상한을 넘으면 원래 제목 쪽을 자른다."""
    base = _COPY_SUFFIX.sub("", source_title)
    n = 1
    while True:
        suffix = f" ({n})"
        title = base[: TITLE_MAX_LENGTH - len(suffix)].rstrip() + suffix
        if title not in taken:
            return title
        n += 1


def check_can_create_map(is_guest: bool) -> None:
    """게스트는 지도를 만들 수 없다(#472) — 403 GUEST_NOT_ALLOWED. 지도 수 상한 검사보다 먼저 부른다."""
    if is_guest:
        raise AppError("GUEST_NOT_ALLOWED")


def pick_successor(
    memberships: Iterable[MembershipEntry], withdrawn: set[str], leaving_user_id: str, *, guests: set[str]
) -> str | None:
    """방장이 빠질 때 방장이 될 사람(#369 확정 3번, 구현 결정 8번). 나가는 사람·탈퇴자·게스트(#472, 게스트는
    방장이 될 수 없다)를 빼고 joined_at이 가장 빠른 구성원, 같으면 memberships.id 순. 넘길 사람이 없으면 None."""
    candidates = [
        m for m in memberships
        if m.user_id != leaving_user_id and m.user_id not in withdrawn and m.user_id not in guests
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: (m.joined_at, m.id)).user_id


def role_in(roster: Iterable[MembershipEntry], user_id: str) -> Role | None:
    return next((m.role for m in roster if m.user_id == user_id), None)


def owner_of(roster: Iterable[MembershipEntry]) -> str | None:
    """지금 방장(memberships.role, #369). 지도당 최대 1명이다(uq_memberships_one_owner_per_map)."""
    return next((m.user_id for m in roster if m.role == "owner"), None)


def check_cover(content_type: str | None, data: bytes) -> str:
    """올린 대표 이미지 검사(#1445). 형식이 COVER_TYPES 밖이거나, 앞 바이트가 그 형식이 아니거나, COVER_MAX_BYTES를 넘으면
    422 COVER_INVALID(detail: limit_bytes, types). 통과하면 저장할 content type을 돌려준다."""
    kind = (content_type or "").split(";")[0].strip().lower()
    sniff = _COVER_MAGIC.get(kind)
    if sniff is None or len(data) > COVER_MAX_BYTES or not sniff(data):
        raise AppError("COVER_INVALID", detail={"limit_bytes": COVER_MAX_BYTES, "types": list(COVER_TYPES)})
    return kind


def cover_url(map_id: str, updated_at: datetime | None) -> str | None:
    """API 기준 상대 주소. 갱신 시각(초)을 붙여 이미지가 바뀌면 주소도 바뀐다 — 그래서 GET이 영구 캐시를 허락할 수 있다."""
    if updated_at is None:
        return None
    # 마이크로초(DB 시각의 정밀도) — 짧은 사이에 두 번 올려도 주소가 달라야 영구 캐시가 옛 이미지를 붙잡지 않는다.
    # float 곱셈 대신 정수로 더해 반올림 오차가 없다.
    return f"/maps/{map_id}/cover?v={int(updated_at.timestamp()) * 1_000_000 + updated_at.microsecond}"


def owner_successor(
    principal: Principal, roster: Iterable[MembershipEntry], withdrawn: set[str], *, guests: set[str]
) -> str | None:
    """요청자가 방장일 때만 후임을 계산한다 — 구성원이 나갈 때는 위임이 없다."""
    if principal.role != "owner":
        return None
    return pick_successor(roster, withdrawn, principal.user_id, guests=guests)


def can_leave(role: Role | None, successor: str | None) -> bool:
    """구성원은 언제나 나갈 수 있다. 방장은 넘길 사람이 있을 때만(#369 9번)."""
    if role is None:
        return False
    return role != "owner" or successor is not None


def check_owner_target(
    roster: Iterable[MembershipEntry], withdrawn: set[str], from_user_id: str, to_user_id: str, *, guests: set[str]
) -> None:
    """방장 직접 넘기기(#468)의 대상 검증. 지금 구성원이고, 탈퇴하지 않았고, 게스트(#472)가 아니고, 나 자신이 아니어야 한다 —
    아니면 422 OWNER_TARGET_INVALID. 구성원이 아닌 사람과 없는 사용자를 구분하지 않는다(존재를 흘리지 않는다)."""
    member_ids = {m.user_id for m in roster}
    if to_user_id == from_user_id or to_user_id not in member_ids or to_user_id in withdrawn or to_user_id in guests:
        raise AppError("OWNER_TARGET_INVALID")


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
        can_edit=can(principal, "map.settings.edit", resource),
        can_manage_invites=can(principal, "invite.revoke", resource),
        can_transfer_owner=can(principal, "owner.transfer", resource),
        can_copy=can(principal, "map.copy", resource),
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
    cover_updated_at: datetime | None = None,
    owner_display_name: str | None = None,
) -> Map:
    """confirmed_count는 shortlist_items 개수 — shortlist.api.count_confirmed로 채운다.
    그래도 매개변수를 Optional로 남긴다 — 값을 못 구하는
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
        color=record.color,
        cover_url=cover_url(record.id, cover_updated_at),
        owner_display_name=owner_display_name,
    )


def to_member_response(
    user_id: str, *, role: Role, display_name: str | None, online: bool | None, is_guest: bool
) -> Member:
    """role은 memberships.role 그대로다(#369 11번 — maps.created_by로 판정하지 않는다).
    display_name은 auth.api.display_names로 채운다(탈퇴자는 '탈퇴한 구성원', #155).
    online은 구성원 목록(list_members)이 realtime.api.online_user_ids로 채운다(#1551). 서버가 모르는 자리(이벤트 페이로드 등)는
    None으로 둔다 — False로 채우지 않는다(그럴싸해 보이는 거짓 fallback이다).
    is_guest는 호출부가 auth.api.guest_user_ids로 구한 값을 넘긴다(#955) — 방장 넘기기 검사(check_owner_target)와 같은 판정이다."""
    return Member(user_id=user_id, role=role, display_name=display_name, online=online, is_guest=is_guest)


def member_joined_event(map_id: str, member: Member) -> Event:
    """docs/events.md member.joined — public 채널, 페이로드는 Member(생략된 필드 제외)."""
    return Event(
        map_id=map_id,
        channel="public",
        type="member.joined",
        payload=member.model_dump(exclude_none=True),
    )


def purge_cutoff(now: datetime) -> datetime:
    """이 시각 이전(같은 시각 포함)에 삭제된 지도는 기간이 찼다 — 정리 대상이고 복구할 수 없다(#464, #1474).
    정리(maps.purge), 복구 판정(is_purge_due), 휴지통 목록이 모두 이 경계를 쓴다."""
    return now - TRASH_RETENTION


def to_map_news(
    since: datetime, new_pin_ids: list[str], reactions: list[dict], names: dict[str, str | None], *, truncated: bool
) -> MapNews:
    """pins.api.list_new_since의 결과를 응답으로 옮긴다(#1556). 사유 글은 문장에 섞지 않고 칸으로 둔다(#717).
    이름을 못 구하면(users 행이 없음) 탈퇴한 구성원으로 표시한다 — 지어낸 이름을 쓰지 않는다."""
    return MapNews(
        since=since,
        new_pin_ids=new_pin_ids,
        new_reactions=[
            NewReaction(
                pin_id=r["pin_id"], user_id=r["user_id"], display_name=names.get(r["user_id"]) or WITHDRAWN_DISPLAY_NAME,
                type=r["type"], reason_text=r.get("reason_text"), reason_chip_ids=list(r.get("reason_chip_ids") or []),
                updated_at=r["updated_at"],
            )
            for r in reactions
        ],
        truncated=truncated,
    )


def is_purge_due(deleted_at: datetime, now: datetime) -> bool:
    """삭제한 지 TRASH_RETENTION이 됐으면 True — 정리 작업이 아직 안 돌았어도 복구할 수 없다(#464). maps.purge가
    지우는 조건과 같은 경계(purge_cutoff)다."""
    return deleted_at <= purge_cutoff(now)


def check_role_can(role: Role | None, map_id: str, user_id: str, action: str) -> None:
    """지도 행을 잠근 뒤 지금 역할로 권한을 다시 판정한다 — 비구성원은 404, 구성원인데 action이 안 되면 403.
    라우터의 판정은 잠금 없이 읽은 값이라 그 사이 방장 위임·나가기가 끼어들 수 있다(복구 #464, 복사 #1446)."""
    if role is None:
        raise AppError("NOT_FOUND")
    if not can(Principal(user_id=user_id, map_id=map_id, role=role), action, Resource(type="map", map_id=map_id)):
        raise AppError("FORBIDDEN")


def check_can_restore(role: Role | None, map_id: str, user_id: str) -> None:
    """복구 권한 판정(#464). 라우터의 restorable_map(요청 초입)과 restore_map(지도 행을 잠근 뒤)이 같은 함수로 판정한다."""
    check_role_can(role, map_id, user_id, "map.restore")


def check_restorable(deleted_at: datetime, now: datetime) -> None:
    if is_purge_due(deleted_at, now):
        raise AppError("MAP_PURGED")


def days_left(deleted_at: datetime, now: datetime) -> int:
    """복구까지 남은 날수(올림). 지금 복구할 수 있는 지도는 1 이상이다."""
    remaining = deleted_at + TRASH_RETENTION - now
    return max(0, -(-remaining // timedelta(days=1)))


def to_trashed_map(
    record: MapRecord, *, deleted_at: datetime, now: datetime, member_count: int, pin_count: int,
) -> TrashedMap:
    region = None
    if record.region_label is not None:
        region = MapRegion(label=record.region_label, lat=record.region_lat, lng=record.region_lng)
    return TrashedMap(
        id=record.id, title=record.title, start_date=record.start_date, end_date=record.end_date,
        region=region, member_count=member_count, pin_count=pin_count, deleted_at=deleted_at,
        purge_at=deleted_at + TRASH_RETENTION, days_left=days_left(deleted_at, now),
    )


def map_restored_event(map_id: str) -> Event:
    """docs/events.md map.restored — public 채널. 복구와 같은 트랜잭션에 기록한다(#464)."""
    return Event(map_id=map_id, channel="public", type="map.restored", payload={"map_id": map_id})


def map_deleted_event(map_id: str) -> Event:
    """docs/events.md map.deleted — public 채널. 삭제와 같은 트랜잭션에 기록한다(#369)."""
    return Event(map_id=map_id, channel="public", type="map.deleted", payload={"map_id": map_id})


def owner_changed_event(map_id: str, from_user_id: str, to_user_id: str) -> Event:
    """docs/events.md owner.changed — public 채널(#468). member.left를 재사용하지 않는다: 두 사람 모두
    지도에 남아 있다."""
    return Event(
        map_id=map_id,
        channel="public",
        type="owner.changed",
        payload={"map_id": map_id, "from_user_id": from_user_id, "to_user_id": to_user_id},
    )

def map_updated_event(map_id: str, updated: NewMap) -> Event:
    """docs/events.md map.updated — public 채널(#465). 요청자 기준 값(permissions)은 싣지 않는다.
    region이 없는 지도는 키 자체를 뺀다."""
    payload = {
        "map_id": map_id,
        "title": updated.title,
        "start_date": updated.start_date.isoformat(),
        "end_date": updated.end_date.isoformat(),
    }
    if updated.region is not None:
        payload["region"] = updated.region.model_dump()
    return Event(map_id=map_id, channel="public", type="map.updated", payload=payload)


def member_left_event(map_id: str, user_id: str, new_owner_user_id: str | None) -> Event:
    """docs/events.md member.left — public 채널(#369). 위임이 없었으면 new_owner_user_id는 null."""
    return Event(
        map_id=map_id,
        channel="public",
        type="member.left",
        payload={"map_id": map_id, "user_id": user_id, "new_owner_user_id": new_owner_user_id},
    )

"""
docs/api-spec.yaml `maps` 태그와 1:1. Map/Invite/Member에는 required 목록이 없다 — 이 모듈이
소유하지 않은 값(Map.confirmed_count, Member.display_name, Member.online)은 채우지 않고
None으로 둔다. 라우터가 response_model_exclude_none=True를 쓰므로 응답에서 키 자체가 빠진다
(0/false/user_id 같은 값으로 채우는 건 실패를 감추는 거짓 fallback이다, docs/code-quality.md).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from authz.schemas import Permissions


class MapRegion(BaseModel):
    """지도 만들기의 지역 검색 결과(#22, 2026-09-28 변경 — PR #132). label/lat/lng 셋 다 있거나
    Map/MapCreateRequest 양쪽 다 region 자체가 없거나(선택 필드) 둘 중 하나다 — 필드 일부만
    있는 반쪽짜리 region은 만들지 않는다(maps/core.py::validate_map_create가 검증)."""

    label: str = Field(max_length=100)
    lat: float
    lng: float


class MapCreateRequest(BaseModel):
    title: str = Field(max_length=100)
    start_date: date
    end_date: date
    region: MapRegion | None = None


class NextOwner(BaseModel):
    """방장이 나가면 방장이 될 사람(#369) — 나가기 확인 창 "나가면 ○○님이 방장이 돼요"용."""

    user_id: str
    display_name: str


class Map(BaseModel):
    id: str
    # 요청자 기준. map은 can_delete(방장만)·can_leave(넘길 사람이 없는 방장은 false)만 채운다(#369).
    permissions: Permissions
    # 요청자의 지금 역할(memberships.role) — 방장을 위임하면 바뀐다. 내 지도 목록의 방장 배지용(#391).
    my_role: Literal["owner", "member"] | None = None
    # maps.created_by == 요청자 — 만든 사람 기록이라 위임돼도 안 바뀐다(my_role과 달라질 수 있다, #391).
    created_by_me: bool | None = None
    # 요청자가 방장이고 넘길 사람이 있을 때만, 상세(GET /maps/{mapId})에서만 채운다(#369).
    next_owner: NextOwner | None = None
    title: str
    start_date: date
    end_date: date
    region: MapRegion | None = None
    member_count: int
    # 삭제되지 않은 공개 핀 수 — pins.api.count_public_pins_by_map으로 센다(#313).
    pin_count: int | None = None
    # shortlist_items 개수 — shortlist에 api.py가 없어 이번 PR은 계산하지 않는다
    # (maps/for_Root.md 항목 5). 값이 없다는 사실 자체를 0으로 흐리지 않는다.
    confirmed_count: int | None = None


class Invite(BaseModel):
    token: str
    url: str
    expires_at: datetime


class InviteSummary(BaseModel):
    """GET /invites/{token} — 로그인 전 수락 화면용. map_id·핀은 포함하지 않는다."""

    title: str
    start_date: date
    end_date: date
    member_count: int
    # 개수만 준다 — 핀의 이름·위치 등 내용은 로그인 전 화면에 주지 않는다(#313).
    pin_count: int | None = None
    inviter_display_name: str
    expires_at: datetime


class Member(BaseModel):
    user_id: str
    # owner = 방장, 나머지 member. memberships.role이 정본이다(#369) — 위임되면 바뀌어서
    # 지도를 만든 사람(maps.created_by)과 다를 수 있다.
    role: Literal["owner", "member"] | None = None
    # users 테이블이 없다(auth #4) — 채울 수 없다.
    display_name: str | None = None
    # 접속 상태 추적이 realtime에 아직 없다 — 채울 수 없다(maps/for_Root.md 항목 5).
    online: bool | None = None

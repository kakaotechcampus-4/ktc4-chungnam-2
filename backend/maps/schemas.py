"""
docs/api-spec.yaml `maps` 태그와 1:1. Map/Invite/Member에는 required 목록이 없다 — 이 모듈이
소유하지 않은 값(Map.confirmed_count, Member.display_name, Member.online)은 채우지 않고
None으로 둔다. 라우터가 response_model_exclude_none=True를 쓰므로 응답에서 키 자체가 빠진다
(0/false/user_id 같은 값으로 채우는 건 실패를 감추는 거짓 fallback이다, docs/code-quality.md).
"""

from datetime import date, datetime

from pydantic import BaseModel


class MapRegion(BaseModel):
    """지도 만들기의 지역 검색 결과(#22, 2026-09-28 변경 — PR #132). label/lat/lng 셋 다 있거나
    Map/MapCreateRequest 양쪽 다 region 자체가 없거나(선택 필드) 둘 중 하나다 — 필드 일부만
    있는 반쪽짜리 region은 만들지 않는다(maps/core.py::validate_map_create가 검증)."""

    label: str
    lat: float
    lng: float


class MapCreateRequest(BaseModel):
    title: str
    start_date: date
    end_date: date
    region: MapRegion | None = None


class Map(BaseModel):
    id: str
    title: str
    start_date: date
    end_date: date
    region: MapRegion | None = None
    member_count: int
    # shortlist_items 개수 — shortlist에 api.py가 없어 이번 PR은 계산하지 않는다
    # (maps/for_Root.md 항목 5). 값이 없다는 사실 자체를 0으로 흐리지 않는다.
    confirmed_count: int | None = None


class Invite(BaseModel):
    token: str
    url: str
    expires_at: datetime


class Member(BaseModel):
    user_id: str
    # users 테이블이 없다(auth #4) — 채울 수 없다.
    display_name: str | None = None
    # 접속 상태 추적이 realtime에 아직 없다 — 채울 수 없다(maps/for_Root.md 항목 5).
    online: bool | None = None

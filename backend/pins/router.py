"""
docs/api-spec.yaml의 pins 태그 엔드포인트 중 #16(목록·생성·삭제)·#17(반응 등록/삭제) 범위.
counts(#141)는 get_counts.
prefix를 두지 않는다 — 경로가 /maps/{mapId}/... 와 /pins/{pinId}로 갈리기 때문이다.

인가는 authz.guard를 거친다(mentor-review-plan.md #56 재정의) — 라우터는 더 이상
membership/403-404 분기를 직접 기억하지 않는다. 에러 응답도 여기서 조립하지 않는다 —
common/errors.py의 앱 레벨 핸들러가 AppError를 봉투로 변환한다.
"""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Principal
from authz.guard import require, require_map_member, require_on_map, require_with_principal
from maps import api as maps_api
from pins import chips, link_import, service
from pins.deps import DbSession
from pins.loaders import load_pin
from pins.models import Pin as PinRow
from pins.schemas import (
    Category, FilterCounts, Pin, PinCreateRequest, BulkPinRequest, BulkPinResult, LinkPreviewRequest, LinkPreviewResult, PinKind, PinResolveRequest, PinUpdateRequest, Reaction, ReactionRequest, ReasonChip,
)
from shortlist import api as shortlist_api

router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

PinsForMap = Depends(require_map_member())          # GET — 조회는 액션이 아니라 멤버십만
PinToCreate = Depends(require_on_map("pin.create"))  # POST — 생성은 실제 액션 판정
PinToEdit = Depends(require_with_principal("pin.edit", load_pin))   # PATCH — 찍은 사람만(AI 추천·확정 제외는 service)
PinToResolve = Depends(require_with_principal("pin.resolve", load_pin))   # POST resolve — 구성원 누구나(#501)
PinToDelete = Depends(require_with_principal("pin.delete", load_pin))
PinForReaction = Depends(require("pin.react", load_pin))
PinForRevert = Depends(require("pin.revert", load_pin))
# 조회는 액션이 아니라 멤버십만 본다(require_map_member와 같은 사정 — 조회 전용 액션이 없다).
# 멤버 액션 하나를 빌려 비구성원 404를 얻는다.
PinToRead = Depends(require("pin.react", load_pin))


@router.get("/categories/{category}/reason-chips", response_model=list[ReasonChip], response_model_exclude_none=True)
def get_reason_chips(category: Category = Path(...)):
    """고정 목록이라 지도와 무관하다 — 라우터 전체의 로그인 의존성(get_current_user)만 걸린다(#60)."""
    return chips.chips_for(category)


@router.get("/maps/{mapId}/pins", response_model=list[Pin], response_model_exclude_none=True)
def get_pins(
    mapId: str = Path(...),
    category: Category | None = Query(default=None),
    kind: PinKind | None = Query(default=None),
    created_by: list[str] | None = Query(default=None),
    principal: Principal = PinsForMap,
    db: Session = DbSession,
):
    return service.list_pins(
        db, map_id=mapId, principal=principal,
        current_member_ids=maps_api.DbMembershipGateway(db).current_member_ids(mapId),
        category=category, kind=kind, created_by=created_by,
    )


@router.get("/maps/{mapId}/counts", response_model=FilterCounts)
def get_counts(
    mapId: str = Path(...),
    principal: Principal = PinsForMap,
    db: Session = DbSession,
):
    return service.count_pins(
        db, map_id=mapId, principal=principal, members_total=maps_api.count_members(db, mapId),
    )


@router.post(
    "/maps/{mapId}/pins",
    response_model=Pin,
    response_model_exclude_none=True,
    status_code=201,
)
def post_pin(
    body: PinCreateRequest,
    mapId: str = Path(...),
    principal: Principal = PinToCreate,
    db: Session = DbSession,
):
    return service.create_pin(db, map_id=mapId, principal=principal, req=body)


@router.post("/maps/{mapId}/pins/link-preview", response_model=LinkPreviewResult, response_model_exclude_none=True)
def post_link_preview(
    body: LinkPreviewRequest,
    mapId: str = Path(...),
    principal: Principal = PinToCreate,
    db: Session = DbSession,
):
    """422 → 404(비구성원) → 429 → 해석. 쓰기 없음."""
    link_import.check_link_preview_rate(principal.user_id, len(body.urls))
    return link_import.preview_links(db, mapId, body.urls)


@router.post("/maps/{mapId}/pins/bulk", response_model=BulkPinResult, response_model_exclude_none=True)
def post_pins_bulk(
    body: BulkPinRequest,
    mapId: str = Path(...),
    principal: Principal = PinToCreate,
    db: Session = DbSession,
):
    return link_import.bulk_create_pins(db, mapId, principal, body.pins)


@router.patch("/pins/{pinId}", response_model=Pin, response_model_exclude_none=True)
def patch_pin(
    body: PinUpdateRequest,
    editable=PinToEdit,
    db: Session = DbSession,
):
    pin, principal = editable
    return service.update_pin(db, pin=pin, principal=principal, req=body)


@router.post("/pins/{pinId}/resolve", response_model=Pin, response_model_exclude_none=True)
def resolve_pin(
    body: PinResolveRequest,
    resolvable=PinToResolve,
    db: Session = DbSession,
):
    pin, principal = resolvable
    return service.resolve_pin(
        db, pin=pin, principal=principal, req=body,
        current_member_ids=maps_api.DbMembershipGateway(db).current_member_ids(pin.map_id),
    )


@router.delete("/pins/{pinId}", status_code=204)
def delete_pin(
    deletable=PinToDelete,
    db: Session = DbSession,
):
    pin, principal = deletable
    # 확정 핀이면 확정 항목을 먼저 정리한다(#235) — 핀이 읽히는 동안이어야 이벤트를 만들 수 있다.
    shortlist_api.remove_for_deleted_pin(db, map_id=pin.map_id, pin_id=str(pin.id), principal=principal)
    service.delete_pin(db, pin=pin)


@router.get("/pins/{pinId}/reactions", response_model=list[Reaction], response_model_exclude_none=True)
def get_reactions(
    pin: PinRow = PinToRead,
    db: Session = DbSession,
):
    return service.list_reactions(db, pin=pin)


@router.put("/pins/{pinId}/reaction", response_model=Reaction, response_model_exclude_none=True)
def put_reaction(
    body: ReactionRequest,
    pin: PinRow = PinForReaction,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    return service.set_reaction(db, pin=pin, viewer_id=user.user_id, req=body)


@router.delete("/pins/{pinId}/reaction", status_code=204)
def delete_reaction(
    pin: PinRow = PinForRevert,
    user: CurrentUser = Depends(get_current_user),
    db: Session = DbSession,
):
    service.delete_reaction(db, pin=pin, viewer_id=user.user_id)

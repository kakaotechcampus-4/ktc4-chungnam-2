"""
docs/api-spec.yaml의 pins 태그 엔드포인트 중 #16(목록·생성·삭제)·#17(반응 등록/삭제) 범위.
counts(#18)는 별도 이슈 — 이 파일에 추가하지 않는다.
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
from authz.guard import require, require_map_member, require_on_map
from pins import service
from pins.deps import DbSession, PlaceGatewayDep
from pins.loaders import load_pin
from pins.models import Pin as PinRow
from pins.ports import PlaceGateway
from pins.schemas import Category, Pin, PinCreateRequest, PinKind, Reaction, ReactionRequest

router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

PinsForMap = Depends(require_map_member())          # GET — 조회는 액션이 아니라 멤버십만
PinToCreate = Depends(require_on_map("pin.create"))  # POST — 생성은 실제 액션 판정
PinToDelete = Depends(require("pin.delete", load_pin))
PinForReaction = Depends(require("pin.react", load_pin))
PinForRevert = Depends(require("pin.revert", load_pin))


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
        db, map_id=mapId, principal=principal, category=category, kind=kind, created_by=created_by,
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
    places: PlaceGateway = PlaceGatewayDep,
):
    return service.create_pin(db, map_id=mapId, principal=principal, req=body, places=places)


@router.delete("/pins/{pinId}", status_code=204)
def delete_pin(
    pin: PinRow = PinToDelete,
    db: Session = DbSession,
):
    service.delete_pin(db, pin=pin)


@router.put("/pins/{pinId}/reaction", response_model=Reaction)
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

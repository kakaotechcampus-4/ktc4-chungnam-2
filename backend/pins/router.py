"""
docs/api-spec.yaml의 pins 태그 엔드포인트 중 #16 범위(목록·생성·삭제) 3개.
반응(#17)·counts(#18)는 별도 이슈 — 이 파일에 추가하지 않는다.
prefix를 두지 않는다 — 경로가 /maps/{mapId}/... 와 /pins/{pinId}로 갈리기 때문이다.
"""

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from pins import service
from pins.deps import (
    CurrentUserId,
    DbSession,
    EventPublisherDep,
    MembershipGatewayDep,
    PlaceGatewayDep,
    require_user_id,
)
from pins.errors import PinError
from pins.ports import EventPublisher, MembershipGateway, PlaceGateway
from pins.schemas import Category, Pin, PinCreateRequest, PinKind

router = APIRouter(tags=["pins"])


def _error_response(exc: PinError) -> JSONResponse:
    body = {"code": exc.code, "message": exc.message}
    if exc.detail is not None:
        body["detail"] = exc.detail
    return JSONResponse(status_code=exc.status_code, content=body)


@router.get("/maps/{mapId}/pins", response_model=list[Pin], response_model_exclude_none=True)
def get_pins(
    mapId: str = Path(...),
    category: Category | None = Query(default=None),
    kind: PinKind | None = Query(default=None),
    created_by: list[str] | None = Query(default=None),
    db: Session = DbSession,
    viewer_id: str | None = CurrentUserId,
    membership: MembershipGateway = MembershipGatewayDep,
):
    try:
        viewer_id = require_user_id(viewer_id)
        pins = service.list_pins(
            db, map_id=mapId, viewer_id=viewer_id, membership=membership,
            category=category, kind=kind, created_by=created_by,
        )
    except PinError as exc:
        return _error_response(exc)
    return pins


@router.post(
    "/maps/{mapId}/pins",
    response_model=Pin,
    response_model_exclude_none=True,
    status_code=201,
)
def post_pin(
    body: PinCreateRequest,
    mapId: str = Path(...),
    db: Session = DbSession,
    viewer_id: str | None = CurrentUserId,
    places: PlaceGateway = PlaceGatewayDep,
    membership: MembershipGateway = MembershipGatewayDep,
    publisher: EventPublisher = EventPublisherDep,
):
    try:
        viewer_id = require_user_id(viewer_id)
        pin = service.create_pin(
            db, map_id=mapId, viewer_id=viewer_id, req=body,
            places=places, membership=membership, publisher=publisher,
        )
    except PinError as exc:
        return _error_response(exc)
    return pin


@router.delete("/pins/{pinId}", status_code=204)
def delete_pin(
    pinId: str = Path(...),
    db: Session = DbSession,
    viewer_id: str | None = CurrentUserId,
    membership: MembershipGateway = MembershipGatewayDep,
    publisher: EventPublisher = EventPublisherDep,
):
    try:
        viewer_id = require_user_id(viewer_id)
        service.delete_pin(db, pin_id=pinId, viewer_id=viewer_id, membership=membership, publisher=publisher)
    except PinError as exc:
        return _error_response(exc)
    return None

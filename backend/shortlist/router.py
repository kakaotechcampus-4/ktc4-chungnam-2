"""
docs/api-spec.yaml `shortlist` 태그 중 확정 리스트 CRUD(GET/POST/DELETE)와 동선 계산
(GET/POST .../route, #103) 범위.

이 커밋에 포함하지 않는 것: `PUT /maps/{mapId}/shortlist/order`(수동 정렬) — 별도 이슈.

인가는 여기서 직접 분기하지 않는다 — GET(확정 리스트·동선 둘 다)은 require_map_member()
(조회는 액션이 아니다), POST/DELETE .../shortlist는 require_with_principal(action, loader)이
loader(shortlist/loaders.py)가 읽은 리소스로 authz.core.can()을 판정한다. resolve_principal은
authz.guard 밖에서 부르지 않는다(authz/tests/test_rule_a_static.py) — 그래서 shortlist/flows.py는
이미 검증된 (obj, principal)만 받는다. POST .../route는 액션 판정이 없는 require_map_member()만
쓴다 — 이유는 아래 RouteForMap 주석 참고.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from authz.core import Principal
from authz.guard import require_map_member, require_with_principal
from pins import api as pins_api
from shortlist import core, flows, service
from shortlist.deps import DbSession
from shortlist.loaders import load_pin_for_confirm, load_shortlist_item
from shortlist.schemas import Route, ShortlistItem

router = APIRouter(tags=["shortlist"], dependencies=[Depends(get_current_user)])

ShortlistForMap = Depends(require_map_member())  # GET — 조회는 멤버십만
PinToConfirm = Depends(require_with_principal("shortlist.add", load_pin_for_confirm))
ItemToUnconfirm = Depends(require_with_principal("shortlist.remove", load_shortlist_item))
# GET/POST .../route 둘 다 순수 멤버십 게이트를 쓴다(#103, 루트 확인 완료) — 루트가
# docs/permissions.md·authz/policy.py에 route.recalculate를 "구성원 누구나"로 등록해뒀지만,
# 라우터는 maps/router.py::MapForInvite(invite.create)와 같은 이유로 최소 침습을 유지한다:
# 지금은 모든 구성원이 동일하게 허용되고 Route 응답에도 permissions 필드가 없어(api-spec.yaml)
# 액션 판정 결과를 내려줄 필요가 없다. 나중에 좁혀야 하면(예: owner만 재계산 허용)
# require_on_map("route.recalculate")로 한 줄 교체하면 된다.
RouteForMap = Depends(require_map_member())


@router.get("/maps/{mapId}/shortlist", response_model=list[ShortlistItem], response_model_exclude_none=True)
def get_shortlist(
    mapId: str = Path(...),
    principal: Principal = ShortlistForMap,
    db: Session = DbSession,
):
    rows = service.list_items(db, map_id=mapId)
    items = []
    for row in rows:
        pin = pins_api.get_pin_response_for_viewer(
            db, pin_id=str(row.pin_id), viewer_id=principal.user_id, principal=principal,
        )
        items.append(core.to_shortlist_item_response(row, pin, principal))
    return items


@router.post(
    "/maps/{mapId}/shortlist",
    response_model=ShortlistItem,
    response_model_exclude_none=True,
    status_code=201,
)
def post_shortlist(confirmed=PinToConfirm, db: Session = DbSession):
    pin_row, principal = confirmed
    return flows.confirm_pin(db, pin_row=pin_row, principal=principal)


@router.delete("/shortlist/{itemId}", status_code=204)
def delete_shortlist(unconfirmed=ItemToUnconfirm, db: Session = DbSession):
    item_row, principal = unconfirmed
    flows.unconfirm_pin(db, item_row=item_row, principal=principal)


@router.get("/maps/{mapId}/route", response_model=list[Route], response_model_exclude_none=True)
def get_route(mapId: str = Path(...), _principal: Principal = RouteForMap, db: Session = DbSession):
    rows = service.list_routes(db, map_id=mapId)
    return [core.to_route_response(row) for row in rows]


@router.post("/maps/{mapId}/route", response_model=list[Route], response_model_exclude_none=True)
def post_route(mapId: str = Path(...), _principal: Principal = RouteForMap, db: Session = DbSession):
    return flows.recalculate_route(db, map_id=mapId)

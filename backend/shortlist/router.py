"""
docs/api-spec.yaml `shortlist` 태그 중 확정 리스트 CRUD(GET/POST/DELETE) 범위.

이 커밋에 포함하지 않는 것: `PUT /maps/{mapId}/shortlist/order`(수동 정렬), `GET|POST
/maps/{mapId}/route`(동선 계산). shortlist/CLAUDE.md "넘지 말 것" — 지역 클러스터링은
recommend의 5-6-1 로직과 같은 원칙을 공유 유틸로 뽑아야 하는데 그 유틸을 어디에 둘지
루트와 상의가 필요하다. for_Root.md에 보고.

인가는 여기서 직접 분기하지 않는다 — GET은 require_map_member()(조회는 액션이 아니다),
POST/DELETE는 require_with_principal(action, loader)이 loader(shortlist/loaders.py)가 읽은
리소스로 authz.core.can()을 판정한다. resolve_principal은 authz.guard 밖에서 부르지 않는다
(authz/tests/test_rule_a_static.py) — 그래서 shortlist/flows.py는 이미 검증된
(obj, principal)만 받는다.
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
from shortlist.schemas import ShortlistItem

router = APIRouter(tags=["shortlist"], dependencies=[Depends(get_current_user)])

ShortlistForMap = Depends(require_map_member())  # GET — 조회는 멤버십만
PinToConfirm = Depends(require_with_principal("shortlist.add", load_pin_for_confirm))
ItemToUnconfirm = Depends(require_with_principal("shortlist.remove", load_shortlist_item))


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

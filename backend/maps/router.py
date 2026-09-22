"""
docs/api-spec.yaml `maps` 태그 5개 엔드포인트. 경로 파라미터는 반드시 `mapId`(camelCase)다 —
authz/guard.py::require_on_map·require_map_member가 이 이름을 하드코딩해서, `map_id`로
쓰면 기동 시점에 바로 실패한다.

`POST /maps`와 `POST /invites/{token}/accept`에는 멤버십 가드가 없다 — 아직 소속될 지도가
없는(또는 방금 발급된 초대로 처음 들어오는) 요청이라, 이 라우터 전체에 걸린 인증
(get_current_user)만 거친다. 빠뜨린 게 아니다.
"""

from fastapi import APIRouter, Depends, Path, Request

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Principal
from authz.guard import require_map_member
from maps import service
from maps.deps import DbSession
from maps.schemas import Invite, Map, Member, MapCreateRequest

router = APIRouter(tags=["maps"], dependencies=[Depends(get_current_user)])

MapForRead = Depends(require_map_member())
MembersForMap = Depends(require_map_member())
# invite.create가 docs/permissions.md에 없다 — require_map_member()로 "구성원 누구나"를
# 최소 침습으로 연다. owner 전용인지는 루트가 정책을 정하면 require_on_map("invite.create")
# 한 줄로 교체한다(maps/for_Root.md 항목 4). require_on_map("map.settings.edit")를 빌려
# 쓰는 안은 기각했다 — 무관한 액션 이름 뒤에 정책 결정을 숨기게 된다.
MapForInvite = Depends(require_map_member())


@router.post("/maps", response_model=Map, response_model_exclude_none=True, status_code=201)
def post_map(
    body: MapCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    return service.create_map(db, req=body, creator_id=user.user_id)


@router.get("/maps/{mapId}", response_model=Map, response_model_exclude_none=True)
def get_map(
    mapId: str = Path(...),
    _principal: Principal = MapForRead,
    db=DbSession,
):
    return service.get_map_response(db, map_id=mapId)


@router.post(
    "/maps/{mapId}/invite", response_model=Invite, response_model_exclude_none=True, status_code=201
)
def post_invite(
    request: Request,
    mapId: str = Path(...),
    _principal: Principal = MapForInvite,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    # base_url = 이 백엔드 서버 자신의 주소다. FE 오리진의 정본이 없어(maps/for_Root.md 항목 8)
    # 이 링크는 지금 브라우저로 바로 열리는 페이지가 아니다(accept는 POST 전용 API라 GET으로
    # 열 수 없다) — 값을 지어내는 대신 이 한계를 그대로 안고 루트에 최우선으로 보고한다.
    base_url = str(request.base_url)
    return service.create_invite(db, map_id=mapId, creator_id=user.user_id, base_url=base_url)


@router.post("/invites/{token}/accept", response_model=Map, response_model_exclude_none=True)
def post_invite_accept(
    token: str = Path(...),
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    return service.accept_invite(db, token=token, user_id=user.user_id)


@router.get("/maps/{mapId}/members", response_model=list[Member], response_model_exclude_none=True)
def get_members(
    mapId: str = Path(...),
    _principal: Principal = MembersForMap,
    db=DbSession,
):
    return service.list_members(db, map_id=mapId)

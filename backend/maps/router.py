"""
docs/api-spec.yaml `maps` 태그 8개 엔드포인트. 경로 파라미터는 반드시 `mapId`(camelCase)다 —
authz/guard.py::require_on_map·require_map_member가 이 이름을 하드코딩해서, `map_id`로
쓰면 기동 시점에 바로 실패한다.

`GET /invites/{token}`만 로그인 없이 열려 있다(public_router, #159).

`POST /maps`와 `POST /invites/{token}/accept`에는 멤버십 가드가 없다 — 아직 소속될 지도가
없는(또는 방금 발급된 초대로 처음 들어오는) 요청이라, 이 라우터 전체에 걸린 인증
(get_current_user)만 거친다. 빠뜨린 게 아니다.

`GET /maps`도 멤버십 가드가 없다 — 특정 mapId 하나를 전제하는 require_map_member()가 아예
성립하지 않는 "내 지도 전체 목록" 조회라, 여기도 인증만 거친다(docs/CHANGELOG-api.md
2026-09-28, #24).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, Request, Response

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Principal, Resource, can
from authz.guard import require_map_member, require_on_map
from common.errors import AppError
from common.settings import settings
from maps import core, flows, service
from maps.deps import DbSession
from maps.schemas import (
    Invite, InviteSummary, Map, MapCreateRequest, MapList, MapUpdateRequest, Member, OwnerTransferRequest,
    TrashedMapList,
)

router = APIRouter(tags=["maps"], dependencies=[Depends(get_current_user)])
# 라우터 단위 의존성은 개별 라우트에서 뺄 수 없다 — 로그인 없이 호출되는 GET /invites/{token}(#23,
# 스펙 security: [])만 인증 없는 별도 라우터에 둔다(auth의 auth_public_router와 같은 패턴).
public_router = APIRouter(tags=["maps"])

MapForRead = Depends(require_map_member())
MembersForMap = Depends(require_map_member())
# 초대 링크 발급은 구성원 누구나다(#4 결정, docs/permissions.md invite.create).
MapForInvite = Depends(require_map_member())
OwnerToTransfer = Depends(require_on_map("owner.transfer"))  # 방장만 — 구성원 403(#468)
InvitesToManage = Depends(require_on_map("invite.revoke"))  # 방장만 — 구성원 403(#467)
MapToEdit = Depends(require_on_map("map.settings.edit"))  # 방장만 — 구성원 403(#465)
MapToDelete = Depends(require_on_map("map.delete"))  # 방장만 — 구성원 403, 비구성원·삭제된 지도 404
MapToLeave = Depends(require_on_map("map.leave"))  # 넘길 사람이 없는 방장 409는 maps.core가 판정


def restorable_map(
    mapId: str = Path(...), user: CurrentUser = Depends(get_current_user), db=DbSession,
) -> Principal:
    """map.restore 판정(#464). require_on_map을 못 쓴다 — 그 가드의 게이트웨이는 삭제된 지도의 역할을 None으로
    돌려줘서(일반 경로는 404) 삭제된 지도를 복구하려는 방장이 항상 404가 된다. 그래서 삭제 여부와 무관하게
    memberships.role을 읽고 판정은 같은 정책 표(authz.can)로 한다. 비구성원·없는 지도는 404, 구성원은 403."""
    role = service.role_in_map(db, map_id=mapId, user_id=user.user_id)
    if role is None:
        raise AppError("NOT_FOUND")
    principal = Principal(user_id=user.user_id, map_id=mapId, role=role)
    if not can(principal, "map.restore", Resource(type="map", map_id=mapId)):
        raise AppError("FORBIDDEN")
    return principal


MapToRestore = Depends(restorable_map)  # 방장만 — 구성원 403, 비구성원·정리된 지도 404


@router.get("/maps", response_model=MapList, response_model_exclude_none=True)
def get_maps(
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    # 상한을 함께 내려 화면이 "n / limit"을 그리고 상한이면 「새 지도」를 미리 막는다(#623).
    return MapList(items=service.list_maps(db, user_id=user.user_id), limit=core.MAP_LIMIT)


# /maps/trash는 /maps/{mapId}보다 앞에 둔다 — 경로 파라미터가 "trash"를 먹지 않게.
@router.get("/maps/trash", response_model=TrashedMapList, response_model_exclude_none=True)
def get_trash(
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    items = service.list_trash(db, user_id=user.user_id, now=datetime.now(timezone.utc))
    return TrashedMapList(items=items, retention_days=core.TRASH_RETENTION.days)


@router.post("/maps", response_model=Map, response_model_exclude_none=True, status_code=201)
def post_map(
    body: MapCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    return service.create_map(db, req=body, creator_id=user.user_id, creator_is_guest=user.is_guest)


@router.get("/maps/{mapId}", response_model=Map, response_model_exclude_none=True)
def get_map(
    mapId: str = Path(...),
    principal: Principal = MapForRead,
    db=DbSession,
):
    return service.get_map_response(db, map_id=mapId, viewer_id=principal.user_id)


@router.patch("/maps/{mapId}", response_model=Map, response_model_exclude_none=True)
def patch_map(
    body: MapUpdateRequest,
    mapId: str = Path(...),
    principal: Principal = MapToEdit,
    db=DbSession,
):
    return service.update_map(db, map_id=mapId, req=body, viewer_id=principal.user_id)


@router.delete("/maps/{mapId}", status_code=204)
def delete_map(
    mapId: str = Path(...),
    principal: Principal = MapToDelete,
    db=DbSession,
):
    service.delete_map(db, map_id=mapId, actor_id=principal.user_id)


@router.post("/maps/{mapId}/restore", response_model=Map, response_model_exclude_none=True)
def restore_map(
    mapId: str = Path(...),
    principal: Principal = MapToRestore,
    db=DbSession,
):
    return service.restore_map(db, map_id=mapId, user_id=principal.user_id)


@router.post("/maps/{mapId}/owner", response_model=Map, response_model_exclude_none=True)
def post_owner(
    body: OwnerTransferRequest,
    mapId: str = Path(...),
    principal: Principal = OwnerToTransfer,
    db=DbSession,
):
    return service.hand_over_owner(db, map_id=mapId, from_user_id=principal.user_id, to_user_id=body.user_id)


@router.delete("/maps/{mapId}/members/me", status_code=204)
def leave_map(
    mapId: str = Path(...),
    principal: Principal = MapToLeave,
    db=DbSession,
):
    flows.leave_map(db, map_id=mapId, user_id=principal.user_id)


@router.post(
    "/maps/{mapId}/invite", response_model=Invite, response_model_exclude_none=True, status_code=201
)
def post_invite(
    request: Request,
    response: Response,
    mapId: str = Path(...),
    _principal: Principal = MapForInvite,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    # FE 오리진 정본이 생겼다(settings.frontend_base_url, 2026-09-23). 못 정했을 때만(dev에서 지워버린 극단적 경우) 예전처럼 백엔드 자신의 주소로
    # 대체한다 — accept가 POST 전용 API라 그 경로는 여전히 브라우저로 바로 열리지 않는다.
    base_url = settings.frontend_base_url or str(request.base_url)
    invite, created = service.create_invite(db, map_id=mapId, creator_id=user.user_id, base_url=base_url)
    if not created:
        response.status_code = 200  # 내가 만든 유효한 링크를 그대로 돌려줬다(#467)
    return invite


@router.get("/maps/{mapId}/invites", response_model=list[Invite], response_model_exclude_none=True)
def get_invites(
    request: Request,
    mapId: str = Path(...),
    _principal: Principal = InvitesToManage,
    db=DbSession,
):
    base_url = settings.frontend_base_url or str(request.base_url)
    return service.list_invites(db, map_id=mapId, base_url=base_url)


@router.delete("/invites/{token}", status_code=204)
def delete_invite(
    token: str = Path(...),
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    # 토큰만으로는 지도를 알 수 없어 require_on_map을 못 쓴다 — 방장 판정은 service.revoke_invite가 한다.
    service.revoke_invite(db, token=token, user_id=user.user_id)


@public_router.get("/invites/{token}", response_model=InviteSummary)
def get_invite_summary(token: str = Path(...), db=DbSession):
    return service.get_invite_summary(db, token=token)


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

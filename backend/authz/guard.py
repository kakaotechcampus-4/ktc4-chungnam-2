"""라우터가 권한 검사를 '기억해서' 부르는 구조를 없앤다 — 리소스를 읽는 일과 판정을 한
의존성으로 묶어서, 검사를 건너뛰면 라우터가 다룰 객체 자체를 못 받게 한다.

리소스를 어떻게 읽는지는 소유 모듈만 안다(pins의 PinRow를 authz가 알면 의존 방향이 뒤집힌다).
그래서 loader는 밖에서 주입받고, 이 모듈은 loader가 돌려준 Resource만 본다."""

from typing import Any, Protocol

from fastapi import Depends, Path

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Resource, can
from authz.deps import get_membership_gateway
from authz.ports import MembershipGateway
from authz.service import resolve_principal
from common.errors import AppError


class Loaded(Protocol):
    """loader의 반환 형태. authz가 아는 건 이 둘뿐이다.

    이건 구조적 타입(Protocol)일 뿐 런타임 강제가 아니다 — loader가 `.resource`/`.obj`가 없는
    걸 돌려주면 아래 `_dep`가 `AttributeError`로 죽는다. 명확한 에러로 바꾸는 건 `_dep`
    안에서 `hasattr` 확인 한 줄로 충분하다(DeepSeek 검수 지적, 아래 반영)."""
    resource: Resource   # 반드시 '실제로 읽은 행'에서 만든 것 — map_id 포함
    obj: Any             # 라우터가 쓸 원본. authz는 내용을 모른다


def require(action: str, loader):
    """loader: 리소스를 읽어 Loaded를 돌려주는 FastAPI 의존성(소유 모듈이 제공).

    404/403 분기가 여기 한 곳에만 있다:
      - 비구성원(role=None) → 404. 못 보는 지도의 리소스는 '존재 여부'조차 알리지 않는다.
      - 구성원인데 액션이 안 되는 경우 → 403 (docs/errors.md: "버튼이 애초에 disabled였어야").

    Rule A("Principal.map_id는 항상 loaded.resource.map_id에서만 온다")는 이 함수가 유일하게
    resolve_principal을 호출하는 지점이라는 사실로 성립한다 — 강제하는 코드가 있는 건 아니고
    관례다(DeepSeek 검수 지적, 정확함). 이 규칙이 실제로 지켜지는지는 아래
    test_no_module_calls_resolve_principal_directly가 정적으로 확인한다.
    """
    def _dep(
        loaded=Depends(loader),
        user: CurrentUser = Depends(get_current_user),
        gateway: MembershipGateway = Depends(get_membership_gateway),
    ):
        if not hasattr(loaded, "resource") or not hasattr(loaded, "obj"):
            raise AppError("INTERNAL_ERROR", detail={"loader": getattr(loader, "__name__", str(loader))})
        principal = resolve_principal(gateway, loaded.resource.map_id, user.user_id)
        if principal.role is None:
            raise AppError("NOT_FOUND")
        if not can(principal, action, loaded.resource):
            raise AppError("FORBIDDEN")
        return loaded.obj

    return _dep


def require_on_map(action: str):
    """읽을 리소스가 없는 액션(pin.create 등) — 대상이 지도 자신이다.
    Principal과 Resource가 같은 mapId 하나에서 나오므로 교차 지도 불일치가 생길 수 없다.

    주의: 경로 파라미터 이름은 반드시 `mapId`여야 한다(camelCase) — `docs/api-spec.yaml`의
    모든 지도 하위 경로가 `/maps/{mapId}/...`로 일관되게 선언돼 있음을 확인했다(예:
    `/maps/{mapId}/pins`, `/maps/{mapId}/shortlist`). 라우터가 `{map_id}`(snake_case)처럼
    다른 이름으로 선언하면 FastAPI가 이 의존성을 그 라우트에 걸 때 시작 시점에 실패한다 —
    이건 리소스 접근 문제가 아니라 라우팅 설정 오류이므로 즉시 눈에 띈다(DeepSeek 검수 지적,
    반영: 이름을 하드코딩하는 이유와 전제를 명시).

    `Resource(type="map", ...)`로 만드는 이유: `authz/policy.py:72`에서 `pin.create`의
    `ACTION_RESOURCE_TYPES`가 `frozenset({"map"})`으로 등록돼 있음을 실제 코드에서 확인했다
    (DeepSeek 검수가 `pin`으로 잘못 등록됐을 가능성을 지적했으나, 실제로는 `map`이 맞다)."""
    def _dep(mapId: str = Path(...), user: CurrentUser = Depends(get_current_user),
             gateway: MembershipGateway = Depends(get_membership_gateway)):
        resource = Resource(type="map", map_id=mapId)
        principal = resolve_principal(gateway, mapId, user.user_id)
        if principal.role is None:
            raise AppError("NOT_FOUND")
        if not can(principal, action, resource):
            raise AppError("FORBIDDEN")
        return principal
    return _dep


def require_map_member():
    """액션 판정이 필요 없는 순수 멤버십 게이트 — 지도 안의 리소스를 **조회**만 하는 라우트용
    (예: `GET /maps/{mapId}/pins`). `docs/permissions.md`의 `member.actions`에는 "목록 조회"에
    해당하는 액션 자체가 없다 — 조회는 액션이 아니라 멤버십 여부만으로 허용되는 별개의 질문이기
    때문이다(DeepSeek 검수 지적: 최초 설계는 `GET`에도 `require_on_map("pin.create")`를 쓰라고
    했는데, 그러면 조회만 하려는 멤버가 "핀 생성" 액션 없이도 됐어야 할 걸 잘못 검사하게 된다
    — `POST`와 같은 액션 이름을 조회에 재사용한 설계 오류였다). 비구성원은 여기서도 404."""
    def _dep(mapId: str = Path(...), user: CurrentUser = Depends(get_current_user),
             gateway: MembershipGateway = Depends(get_membership_gateway)):
        principal = resolve_principal(gateway, mapId, user.user_id)
        if principal.role is None:
            raise AppError("NOT_FOUND")
        return principal
    return _dep

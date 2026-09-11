"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시간·전역상태를 건드리지 않고,
입력을 받아 값을 반환할 뿐이라 모의 객체 없이 직접 호출해서 테스트한다.

이 모듈은 "할 수 있는가"만 답한다(authz/CLAUDE.md) — 실제 액션 실행은 각 리소스 모듈의 몫이고,
403을 던지는 일도 이 모듈이 하지 않는다. pins가 세운 "비공개 404가 구성원 403보다 먼저"(가드레일 1)
같은 순서 규칙은 리소스 모듈마다 다를 수 있어 여기서 강제하지 않는다.
"""

from dataclasses import dataclass

from authz.policy import ACTION_RESOURCE_TYPES, AUTHOR_CONSTRAINED_ACTIONS, POLICY, ResourceType, Role
from authz.schemas import Permissions


@dataclass(frozen=True)
class Principal:
    """판정 대상 사용자. role은 이미 특정 지도 기준으로 조회된 값이다 — map_id를 함께 들고 있어야
    can()이 그 role을 엉뚱한 지도의 리소스에 잘못 적용하는 걸 막을 수 있다."""

    user_id: str
    map_id: str
    role: Role | None  # None = 비구성원


@dataclass(frozen=True)
class Resource:
    """판정 대상 리소스. author_id는 evidence_lines.author_id 또는 recommend_runs.requested_by —
    리소스 종류마다 무엇을 가리키는지가 다르므로 호출부가 맞게 채워야 한다."""

    type: ResourceType
    map_id: str
    author_id: str | None = None
    kind: str | None = None  # pins.kind — 상태 게이팅 전용, can()은 이 값을 쓰지 않는다


def can(user: Principal, action: str, resource: Resource) -> bool:
    """docs/permissions.md의 역할 → (범위, 액션) 선언을 해석한다.

    호출 순서가 그대로 판정 순서다:
    0. principal과 resource의 map_id가 다르면 ValueError. role은 특정 지도 기준으로 조회된
       값인데 그 지도를 안 들고 다니면, 지도 A에서 뽑은 role로 지도 B의 리소스를 판정하는
       교차 지도 권한 상승이 조용히 통과한다. 이건 판정 결과가 아니라 호출부 배선 버그이므로
       False로 삼키지 않고 즉시 터뜨린다(실패를 감추지 않는다 — docs/code-quality.md).
    1. 비구성원(role=None)은 자신이 작성자여도 전부 False. author는 permissions.md 25행이
       "얹히는 추가 범위"로, 41행이 역할 누적으로 정의하므로 member 위에만 얹힌다 — 독립된
       역할이 아니다.
    2. 액션-리소스 종류 결합이 안 맞으면 False (recommend.publish를 pin에 묻는 등 타입 혼동 차단).
    3. AUTHOR_CONSTRAINED_ACTIONS(recommend.publish)인데 작성자 본인이 아니면 False.
    4~5. member/author/owner 중 부여된 역할들을 계산하고, 그중 하나라도 액션+범위를 통과시키면 True.
    """
    if user.map_id != resource.map_id:
        # 전제: Principal은 항상 리소스에서 읽은 map_id로만 만들어진다(Rule A,
        # docs/permissions.md "권한을 어디서 강제하는가"). 두 개의 독립된 id를 받는 요청은
        # authz.guard의 loader가 여기 도달하기 전에 대조해서 404로 끝낸다(Rule B) — 예:
        # POST /maps/{mapId}/shortlist가 mapId(경로)와 pin_id(바디)를 따로 받는 경우.
        # 이 두 규칙이 지켜지는 한 여기 도달하는 것 자체가 호출부 배선 버그다.
        raise ValueError(
            f"principal.map_id({user.map_id!r})와 resource.map_id({resource.map_id!r})가 다릅니다 — "
            "이 role은 다른 지도 기준으로 조회된 값입니다"
        )

    if user.role is None:
        return False

    valid_types = ACTION_RESOURCE_TYPES.get(action)
    if valid_types is None or resource.type not in valid_types:
        return False

    if action in AUTHOR_CONSTRAINED_ACTIONS and resource.author_id != user.user_id:
        return False

    granted_roles: list[str] = ["member"]
    if user.role == "owner":
        granted_roles.append("owner")
    if resource.author_id is not None and resource.author_id == user.user_id:
        granted_roles.append("author")

    for role in granted_roles:
        spec = POLICY[role]
        if action not in spec.actions:
            continue
        if role == "author" and resource.type not in spec.scope:
            continue
        return True

    return False


def _pin_permissions(user: Principal, resource: Resource) -> Permissions:
    """kind==확정 게이팅은 permissions.md에 없는 상태 규칙이라 can()이 아니라 여기 둔다
    (for_Root.md 참고). backend/pins/core.py::pin_permissions와 응답이 바이트 단위로 같아야
    한다 — #56 이관 시 FE가 받는 JSON이 바뀌면 안 된다."""
    can_add = can(user, "shortlist.add", resource) and resource.kind != "확정"
    can_remove = can(user, "shortlist.remove", resource) and resource.kind == "확정"
    return Permissions(
        can_react=can(user, "pin.react", resource),
        can_revert=can(user, "pin.revert", resource),
        can_delete=can(user, "pin.delete", resource),
        can_add_to_shortlist=can_add,
        can_remove_from_shortlist=can_remove,
    )


def _evidence_line_permissions(user: Principal, resource: Resource) -> Permissions:
    """author 본인만 can_disable=True. 나머지 필드는 의미가 없어 None으로 남긴다
    (response_model_exclude_none=True가 응답에서 걷어낸다)."""
    return Permissions(can_disable=can(user, "evidence.disable", resource))


def _shortlist_item_permissions(user: Principal, resource: Resource) -> Permissions:
    """can_add_to_shortlist는 항상 False — 이미 리스트에 올라간 항목이라 "추가"가 의미가 없다.
    shortlist(#7) 미구현 상태에서의 추정 — for_Root.md에 보고."""
    return Permissions(
        can_add_to_shortlist=False,
        can_remove_from_shortlist=can(user, "shortlist.remove", resource),
    )


def permissions_for(user: Principal, resource: Resource) -> Permissions:
    """모든 리소스 응답에 주입하는 permissions 객체 — 다른 모듈이 부르는 공용 진입점
    (authz/CLAUDE.md "모든 리소스 응답에 permissions 객체를 계산해 주입하는 공통 유틸").

    리소스 종류별로 의미 있는 필드만 채우고 나머지는 None으로 둔다. map·candidate는 계약에
    permissions 필드가 없어(candidate는 for_Root.md에 계약 갭으로 보고됨) 지원하지 않는다 —
    호출하면 무엇이 비어 있는지 알 수 있도록 예외를 던진다."""
    if resource.type == "pin":
        return _pin_permissions(user, resource)
    if resource.type == "evidence_line":
        return _evidence_line_permissions(user, resource)
    if resource.type == "shortlist_item":
        return _shortlist_item_permissions(user, resource)
    raise ValueError(
        f"resource.type={resource.type!r}에는 permissions 빌더가 없습니다 — "
        "api-spec.yaml에 permissions 필드가 없는 리소스입니다(for_Root.md 참고)"
    )

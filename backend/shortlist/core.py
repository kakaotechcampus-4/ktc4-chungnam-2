"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시간·전역상태를 건드리지 않는다.
"""

from authz.core import Principal, Resource, permissions_for
from common.events import Event
from pins import api as pins_api
from pins.schemas import Pin
from shortlist.schemas import Route, RouteLeg, ShortlistItem


def to_shortlist_item_response(row, pin: Pin, principal: Principal) -> ShortlistItem:
    """row는 shortlist_items ORM 행(id/added_by/visit_order만 쓴다) — pin은 pins.api가 이미
    조립해 돌려준 완성된 Pin(그 자체의 permissions 포함)을 그대로 얹는다.

    can_add_to_shortlist는 항상 False로 나온다(authz/core.py::_shortlist_item_permissions —
    이미 리스트에 올라간 항목이라 "추가"가 의미 없다는 그쪽의 기존 결정을 그대로 따른다)."""
    permissions = permissions_for(principal, Resource(type="shortlist_item", map_id=row.map_id))
    return ShortlistItem(
        id=str(row.id), pin=pin, visit_order=row.visit_order, added_by=row.added_by, permissions=permissions,
    )


def _public_item_payload(item: ShortlistItem) -> dict:
    """공개 채널 페이로드는 보는 사람마다 다른 값을 담지 않는다(docs/events.md) — 행위자의 my_reaction과
    permissions(항목·핀 둘 다)를 뺀다. 핀 쪽은 pins가 쓰는 공개 페이로드 규칙을 그대로 쓴다(#241)."""
    payload = item.model_dump(exclude_none=True, exclude={"pin", "permissions"})
    payload["pin"] = {k: v for k, v in pins_api.public_pin_payload(item.pin).items() if k != "permissions"}
    return payload


def shortlist_changed_event(item: ShortlistItem, action: str) -> Event:
    """docs/events.md shortlist.changed. 확정 리스트에는 비공개 개념이 없다 — 확정된 핀은
    flows.confirm_pin이 이미 visibility=public인 핀만 통과시키므로(가드레일 1), pin.created류와
    달리 채널 분기가 필요 없다. action은 'added'|'removed'|'reordered'다. 'reordered'는 정렬에 들어간
    항목마다 하나씩(새 visit_order를 담아) 발행한다 — payload가 항목 하나 단위라서다."""
    return Event(
        map_id=item.pin.map_id, channel="public", type="shortlist.changed",
        payload={"item": _public_item_payload(item), "action": action},
    )


def reorder_mismatch(current_ids: list[str], requested_ids: list[str]) -> dict | None:
    """수동 정렬 요청이 현재 확정 항목과 정확히 같은 집합이 아니면 이유를 돌려준다(같으면 None).
    중복은 집합 비교로는 안 잡히므로 따로 센다."""
    current, requested = set(current_ids), set(requested_ids)
    if len(requested_ids) == len(requested) and requested == current:
        return None
    return {
        "duplicated": sorted({i for i in requested_ids if requested_ids.count(i) > 1}),
        "missing": sorted(current - requested),
        "unknown": sorted(requested - current),
    }


def to_route_response(row) -> Route:
    """row는 shortlist.models.Route ORM 행 — jsonb로 저장된 legs를 RouteLeg로 되살린다."""
    return Route(
        region_label=row.region_label,
        ordered_pin_ids=list(row.ordered_pin_ids),
        total_distance_m=row.total_distance_m,
        legs=[RouteLeg(**leg) for leg in row.legs],
    )


def route_recalculated_event(map_id: str, routes: list[Route]) -> Event:
    """docs/events.md route.recalculated — data는 다른 이벤트처럼 객체로 감싸지 않고 Route[]
    그대로다. common.events.Event.payload는 dict로 타입힌트돼 있지만 `@dataclass`라 런타임
    강제는 없다(pydantic이 아니다) — 이 이벤트에 한해 리스트를 그대로 담는다. 타입힌트를
    `dict | list`로 넓히는 게 더 정확하겠지만 common은 여러 모듈이 공유해 이 커밋에서는
    건드리지 않았다 — for_Root.md에 제안으로 남긴다."""
    return Event(
        map_id=map_id, channel="public", type="route.recalculated",
        payload=[route.model_dump(exclude_none=True) for route in routes],
    )

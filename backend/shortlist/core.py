"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시간·전역상태를 건드리지 않는다.
"""

from authz.core import Principal, Resource, permissions_for
from common.events import Event
from pins.schemas import Pin
from shortlist.schemas import ShortlistItem


def to_shortlist_item_response(row, pin: Pin, principal: Principal) -> ShortlistItem:
    """row는 shortlist_items ORM 행(id/added_by/visit_order만 쓴다) — pin은 pins.api가 이미
    조립해 돌려준 완성된 Pin(그 자체의 permissions 포함)을 그대로 얹는다.

    can_add_to_shortlist는 항상 False로 나온다(authz/core.py::_shortlist_item_permissions —
    이미 리스트에 올라간 항목이라 "추가"가 의미 없다는 그쪽의 기존 결정을 그대로 따른다)."""
    permissions = permissions_for(principal, Resource(type="shortlist_item", map_id=row.map_id))
    return ShortlistItem(
        id=str(row.id), pin=pin, visit_order=row.visit_order, added_by=row.added_by, permissions=permissions,
    )


def shortlist_changed_event(item: ShortlistItem, action: str) -> Event:
    """docs/events.md shortlist.changed. 확정 리스트에는 비공개 개념이 없다 — 확정된 핀은
    flows.confirm_pin이 이미 visibility=public인 핀만 통과시키므로(가드레일 1), pin.created류와
    달리 채널 분기가 필요 없다. action은 'added'|'removed' 둘뿐이다(수동 정렬 'reordered'는
    이 커밋 범위 밖 — for_Root.md 참고)."""
    return Event(
        map_id=item.pin.map_id, channel="public", type="shortlist.changed",
        payload={"item": item.model_dump(exclude_none=True), "action": action},
    )

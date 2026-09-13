"""
핀 확정/제외 — pins 모듈 테이블(kind)까지 같은 트랜잭션에서 바꾸는 유일한 지점
(mentor-review-plan.md "결정 — shortlist/flows.py::confirm_pin"). shortlist는 이 파일에서만
pins.api를 부른다 — service.py는 pins를 모른다.

인가는 이 파일이 아니라 router.py가 authz.guard.require_with_principal(loader)로 이미 끝낸
뒤에 호출된다(authz/tests/test_rule_a_static.py — resolve_principal은 authz.guard 밖에서
직접 부르지 않는다). 여기서는 이미 검증된 pin_row/item_row/principal만 받아 pins.api 호출과
shortlist_items 쓰기를 조립한다.
"""

from common.events import record_event
from pins import api as pins_api
from shortlist import core, service
from shortlist.schemas import ShortlistItem


def confirm_pin(db, *, pin_row, principal) -> ShortlistItem:
    map_id, pin_id = pin_row.map_id, str(pin_row.id)

    row, created = service.add_item(db, map_id=map_id, pin_id=pin_id, added_by=principal.user_id)
    pin = pins_api.get_pin_response_for_viewer(db, pin_id=pin_id, viewer_id=principal.user_id, principal=principal)
    item = core.to_shortlist_item_response(row, pin, principal)
    if not created:
        return item  # 멱등 빠른 경로 — pins.kind 재변경도 이벤트도 없다

    pins_api.mark_confirmed(db, pin_id=pin_id, map_id=map_id)
    record_event(db, core.shortlist_changed_event(item, "added"))
    return item


def unconfirm_pin(db, *, item_row, principal) -> None:
    pin_id, map_id = str(item_row.pin_id), item_row.map_id

    # DeepSeek 검수 지적(mentor-review-plan.md) — delete_item 이후 row 속성에 접근하면
    # DetachedInstanceError 위험이 있다. 이벤트 페이로드(핀 응답 포함)를 삭제 전에 전부 만든다.
    pin = pins_api.get_pin_response_for_viewer(db, pin_id=pin_id, viewer_id=principal.user_id, principal=principal)
    item = core.to_shortlist_item_response(item_row, pin, principal)
    event = core.shortlist_changed_event(item, "removed")

    service.delete_item(db, str(item_row.id))
    pins_api.unmark_confirmed(db, pin_id=pin_id, map_id=map_id)
    record_event(db, event)

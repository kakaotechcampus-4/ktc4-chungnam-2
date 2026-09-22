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
from common.geo import Point
from pins import api as pins_api
from shortlist import core, routing, service
from shortlist.schemas import Route, ShortlistItem


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


def recalculate_route(db, *, map_id: str) -> list[Route]:
    """「동선 짜주기」(POST /maps/{mapId}/route, #103) — 수동 트리거로만 호출된다
    (shortlist/CLAUDE.md "책임"). 확정 리스트(add_order 순)의 핀 좌표를 pins.api를 통해서만
    읽고(다른 모듈 테이블 직접 쿼리 금지, backend/CLAUDE.md), 순수 계산(routing.compute_routes)
    결과를 저장 후 route.recalculated를 발행한다.

    좌표가 없는 pin_id(삭제된 핀 등, get_coordinates_for_pins가 조용히 빼는 경우)는 건너뛴다 —
    KeyError로 500을 내는 대신, 그 핀만 이번 동선에서 빠지는 쪽이 맞다(Antigravity 검수 지적).
    POST 응답도 GET과 같은 정렬(service.list_routes)을 거쳐 반환한다 — 그래야 POST 직후 응답과
    바로 이어지는 GET 응답의 순서가 어긋나지 않는다."""
    items = service.list_items(db, map_id=map_id)
    pin_ids = [str(item.pin_id) for item in items]
    coordinates = pins_api.get_coordinates_for_pins(db, pin_ids)
    points = [
        Point(id=pin_id, lat=coordinates[pin_id][0], lng=coordinates[pin_id][1])
        for pin_id in pin_ids
        if pin_id in coordinates
    ]

    routes = routing.compute_routes(points)
    service.replace_routes(db, map_id=map_id, routes=routes)
    # DB에 쓴 뒤 같은 정렬(region_label 오름차순)로 다시 읽어 이벤트·응답 둘 다 GET과 순서를
    # 맞춘다 — routing.compute_routes가 만든 순서(계산 순)와 list_routes의 정렬 기준이 다르면
    # POST 직후 응답이 바로 이어지는 GET과 어긋난다(Antigravity 검수 지적).
    saved_routes = [core.to_route_response(row) for row in service.list_routes(db, map_id=map_id)]
    record_event(db, core.route_recalculated_event(map_id, saved_routes))
    return saved_routes

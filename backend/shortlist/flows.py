"""
핀 확정/제외 — pins 모듈 테이블(kind)까지 같은 트랜잭션에서 바꾸는 유일한 지점
(mentor-review-plan.md "결정 — shortlist/flows.py::confirm_pin"). shortlist는 이 파일에서만
pins.api를 부른다 — service.py는 pins를 모른다.

인가는 이 파일이 아니라 router.py가 authz.guard.require_with_principal(loader)로 이미 끝낸
뒤에 호출된다(authz/tests/test_rule_a_static.py — resolve_principal은 authz.guard 밖에서
직접 부르지 않는다). 여기서는 이미 검증된 pin/item_row/principal만 받아 pins.api 호출과
shortlist_items 쓰기를 조립한다.
"""

from common.events import record_event
from common.geo import Point
from maps import api as maps_api
from pins import api as pins_api
from shortlist import core, routing, service
from shortlist.schemas import Route, Schedule, ShortlistItem


def confirm_pin(db, *, pin, principal) -> ShortlistItem:
    map_id, pin_id = pin.map_id, pin.id

    row, created = service.add_item(db, map_id=map_id, pin_id=pin_id, added_by=principal.user_id)
    pin_response = pins_api.get_pin_response_for_viewer(db, pin_id=pin_id, viewer_id=principal.user_id, principal=principal)
    item = core.to_shortlist_item_response(row, pin_response, principal)
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

    service.lock_shortlist(db, map_id)  # 동시 수동 정렬이 이미 사라진 행을 정렬 대상으로 읽지 않게
    service.delete_item(db, str(item_row.id))
    pins_api.unmark_confirmed(db, pin_id=pin_id, map_id=map_id)
    record_event(db, event)


def reorder_shortlist(db, *, map_id: str, item_ids: list[str], principal) -> list[ShortlistItem]:
    """PUT /maps/{mapId}/shortlist/order(#142) — visit_order만 바꾼다. 동선(routes)은 건드리지
    않고 route.recalculated도 내지 않는다. shortlist.changed(reordered) 하나를 같은 트랜잭션에 기록한다."""
    rows = service.reorder_items(db, map_id=map_id, item_ids=item_ids)
    items = []
    for row in rows:
        pin = pins_api.get_pin_response_for_viewer(
            db, pin_id=str(row.pin_id), viewer_id=principal.user_id, principal=principal,
        )
        items.append(core.to_shortlist_item_response(row, pin, principal))
    _record_reordered(db, items)
    return items


def _record_reordered(db, items: list[ShortlistItem]) -> None:
    """순서 바꾸기·일정 저장 한 번에 shortlist.changed(reordered) 하나(#1274). 받는 쪽은 목록을 다시 받아
    순서를 보므로 item은 첫 항목만 싣는다. 항목마다 내면 확정 20곳에 구성원마다 다시 받기가 수십 번 나갔다."""
    if items:
        record_event(db, core.shortlist_changed_event(items[0], "reordered"))


def export_shortlist(db, *, map_id: str, principal, fmt: str) -> tuple[str, str, str]:
    """GET /maps/{mapId}/shortlist/export(#471) — (본문, media_type, Content-Disposition). 읽기만 하고
    확정 순서(service.list_items)대로 pins.api로 핀을 받아 core의 순수 함수로 직렬화한다."""
    rows = []
    previous_date = object()
    order = 0
    for item in service.list_items(db, map_id=map_id):
        if item.scheduled_date != previous_date:
            order = 0
            previous_date = item.scheduled_date
        order += 1
        pin = pins_api.get_pin_response_for_viewer(
            db, pin_id=str(item.pin_id), viewer_id=principal.user_id, principal=principal,
        )
        rows.append(core.to_export_row(order, pin, item.scheduled_date.isoformat() if item.scheduled_date else ""))
    disposition = core.export_content_disposition(maps_api.get_map_title(db, map_id), fmt)
    if fmt == "csv":
        return core.render_csv(rows), "text/csv; charset=utf-8", disposition
    return core.render_txt(rows), "text/plain; charset=utf-8", disposition


def recalculate_route(db, *, map_id: str) -> list[Route]:
    """「동선 짜주기」(POST /maps/{mapId}/route, #103) — 수동 트리거로만 호출된다
    (shortlist/CLAUDE.md "책임"). 확정 리스트(add_order 순)의 핀 좌표를 pins.api를 통해서만
    읽고(다른 모듈 테이블 직접 쿼리 금지, backend/CLAUDE.md), 순수 계산(routing.compute_routes)
    결과를 저장 후 route.recalculated를 발행한다.

    좌표가 없는 pin_id(삭제된 핀 등, get_coordinates_for_pins가 조용히 빼는 경우)는 건너뛴다 —
    KeyError로 500을 내는 대신, 그 핀만 이번 동선에서 빠지는 쪽이 맞다(Antigravity 검수 지적).
    POST 응답도 GET과 같은 정렬(service.list_routes)을 거쳐 반환한다 — 그래야 POST 직후 응답과
    바로 이어지는 GET 응답의 순서가 어긋나지 않는다."""
    items = service.list_items_by_added(db, map_id=map_id)
    pin_ids = [str(item.pin_id) for item in items]
    coordinates = pins_api.get_coordinates_for_pins(db, pin_ids)
    points = [
        Point(id=pin_id, lat=coordinates[pin_id][0], lng=coordinates[pin_id][1])
        for pin_id in pin_ids
        if pin_id in coordinates
    ]

    routes = routing.compute_routes(points)
    service.replace_routes(db, map_id=map_id, routes=routes)
    # DB에 쓴 뒤 같은 정렬(구역 번호 오름차순)로 다시 읽어 이벤트·응답 둘 다 GET과 순서를
    # 맞춘다 — routing.compute_routes가 만든 순서(계산 순)와 list_routes의 정렬 기준이 다르면
    # POST 직후 응답이 바로 이어지는 GET과 어긋난다(Antigravity 검수 지적).
    saved_routes = [core.to_route_response(row) for row in service.list_routes(db, map_id=map_id)]
    record_event(db, core.route_recalculated_event(map_id, saved_routes))
    return saved_routes


def schedule(db, *, map_id, principal, update=None):
    """GET·PUT /maps/{mapId}/shortlist/schedule. 읽기(update=None)는 잠그지 않는다(#1435) — 지도 행 FOR UPDATE와
    advisory lock을 읽기도 잡으면 구성원마다 몰리는 다시 받기(GET)가 저장(PUT)과 같은 줄에 서서 서로를 기다린다
    (GET 항목마다 핀 응답을 만드는 동안 잠금을 쥔다). 읽기는 지도가 살아 있는지만 잠금 없이 본다. 저장은 지도 행과
    확정 리스트를 잠가 같은 지도의 확정 리스트 변경과 줄을 선다(기존 그대로)."""
    from common.errors import AppError

    if update is None:
        map_info = maps_api.get_map_for_agent(db, map_id)
        if map_info is None or map_info["deleted"]:
            raise AppError("NOT_FOUND")
    else:
        if not maps_api.lock_map_if_alive(db, map_id):
            raise AppError("NOT_FOUND")
        map_info = maps_api.get_map_for_agent(db, map_id)
        service.lock_shortlist(db, map_id)
    start, end = map_info["start_date"], map_info["end_date"]
    if update is None:
        rows = service.list_items(db, map_id=map_id)
    else:
        rows = service.replace_schedule(db, map_id=map_id, start_date=start, end_date=end,
                                        version=update.version, groups=update.groups)
    items = []
    for row in rows:
        try:
            pin = pins_api.get_pin_response_for_viewer(db, pin_id=str(row.pin_id), viewer_id=principal.user_id, principal=principal)
        except AppError as error:
            if update is None and error.code == "NOT_FOUND":
                continue  # 잠금 없이 읽는 사이 핀이 지워졌다 — 그 항목만 빼고 돌려준다(version은 행 기준이라 다음 저장이 STALE로 새로 받게 한다)
            raise
        items.append(core.to_shortlist_item_response(row, pin, principal))
    if update is not None:
        _record_reordered(db, items)
    return Schedule(start_date=start, end_date=end, version=service.schedule_version(start, end, rows), items=items)

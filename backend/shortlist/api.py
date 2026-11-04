"""
다른 모듈이 shortlist를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 확정 개수 집계와, 핀 삭제 시 확정 항목 정리(#235)다.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from authz.core import Principal
from common.errors import AppError
from maps import api as maps_api
from pins import api as pins_api
from shortlist import flows, service
from shortlist.models import ShortlistItem


def count_confirmed(db: Session, *, map_id: str) -> int:
    """maps의 Map.confirmed_count가 쓴다. shortlist_items는 상태 컬럼이
    없어 행 존재 자체가 확정이다(제외는 행을 지운다, service.py::remove_item) — list_items와
    같은 기준(map_id만)으로 센다. 소프트삭제된 핀의 행이 섞여 있어도 그대로 센다 —
    get_coordinates_for_pins가 동선 계산에서만 그런 행을 제외하는 것과는 별개 판단이다."""
    return db.execute(
        select(func.count()).select_from(ShortlistItem).where(ShortlistItem.map_id == map_id)
    ).scalar_one()


def remove_for_deleted_pin(db: Session, *, map_id: str, pin_id: str, principal: Principal) -> bool:
    """핀을 삭제하기 **직전에** pins가 부른다(#235). 그 핀이 확정 리스트에 있으면 항목을 같은
    트랜잭션에서 지우고 shortlist.changed(removed)를 낸다 — 안 지우면 확정 리스트 조회가 삭제된
    핀 때문에 통째로 404가 되고 confirmed_count가 어긋난다. 핀이 아직 읽혀야 이벤트 페이로드(핀 응답)를
    만들 수 있어서 소프트 삭제보다 먼저 부른다. 확정 항목이 없으면 아무것도 하지 않는다.
    지운 항목이 있었으면 True, 없었으면 False를 돌려준다 — pins가 `deleted_was_confirmed`로 기록해 복구(restore_confirmed, #1013)
    때 확정으로 되올린다. 같은 핀을 다시 부르면 False(멱등).
    동선(route.recalculated)은 확정 리스트 변경만으로는 발행하지 않는다(docs/events.md) —
    일반 제외(DELETE /shortlist/{itemId})와 같은 규칙이다."""
    item_row = db.execute(
        select(ShortlistItem).where(ShortlistItem.map_id == map_id, ShortlistItem.pin_id == uuid.UUID(pin_id))
    ).scalar_one_or_none()
    if item_row is not None:
        flows.unconfirm_pin(db, item_row=item_row, principal=principal)
    return item_row is not None


def list_items_for_agent(db: Session, *, map_id: str) -> list[dict]:
    """agent 스냅샷(docs/agent-v2.md 12.7, #522)이 부른다 — `[{pin_id, added_by, added_at}]`, added_at 순.
    count_confirmed와 같은 기준(map_id만)이라 소프트 삭제된 핀의 항목도 그대로 담는다. 읽기 전용, 커밋하지 않는다."""
    return service.list_items_for_agent(db, map_id=map_id)


def get_schedule_for_agent(db: Session, *, map_id: str) -> dict:
    """AI 코스(#1238)가 부른다 — `{start_date, end_date, version, items: [{pin_id, added_by, added_at, scheduled_date,
    visit_order}]}`. 여행 기간은 maps.api에서 받는다. items 순서와 version은 GET /maps/{mapId}/shortlist/schedule과
    같다(날짜 순, 미배정은 뒤, 같은 날은 visit_order 순). scheduled_date·visit_order는 미배정이면 None이다.
    list_items_for_agent와 달리 일정 열을 담고 순서가 다르다. 소프트 삭제된 핀의 항목도 담는다(count_confirmed와 같은 기준).
    읽기 전용이고 잠그지 않으며 커밋하지 않는다. 없거나 삭제된 지도는 404 NOT_FOUND."""
    info = maps_api.get_map_for_agent(db, map_id)
    if info is None or info["deleted"]:
        raise AppError("NOT_FOUND")
    return service.schedule_for_agent(db, map_id=map_id, start_date=info["start_date"], end_date=info["end_date"])


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 shortlist_items·routes만 지우고 테이블 이름 →
    지운 행 수를 돌려준다. 핀(pins)보다 먼저 불러야 한다(shortlist_items.pin_id가 pins를 참조). 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#560)가 부른다 — from_user가 추가한 확정 항목(shortlist_items.added_by)을 to_user로 옮기고
    테이블 이름 → 옮긴 행 수를 돌려준다. 멱등이고 같은 id면 아무것도 하지 않는다. 커밋하지 않는다."""
    return service.reassign_user(db, from_user_id=from_user_id, to_user_id=to_user_id)


def restore_confirmed(db: Session, *, pin_id: str) -> bool:
    """핀 휴지통 복구(#1013)가 부른다 — 삭제 때 확정이었던 핀을 확정 리스트 맨 뒤로 다시 올리고 kind를 확정으로 되돌린다.
    **핀이 이미 복구된(deleted_at이 비워진) 뒤에 부른다** — 삭제된 핀은 pins.api가 404로 본다. 새로 올렸으면 True,
    이미 확정 리스트에 있으면 False(멱등). 확정 개수 상한은 없어 한도로 거절하는 경우가 없다. 추가한 사람(added_by)은
    원래 항목이 삭제 때 지워져 알 수 없으므로 핀을 찍은 사람(created_by)으로 쓴다. shortlist.changed는 내지 않는다 —
    화면은 pin.restored에서 확정 리스트를 다시 읽고(docs/events.md), 동선은 수동 트리거로만 재계산된다.
    커밋하지 않는다. 핀이 없거나 삭제된 상태면 404 NOT_FOUND."""
    pin = pins_api.get_pin_for_viewer(db, pin_id=pin_id, viewer_id="")
    created = service.restore_item(db, map_id=pin.map_id, pin_id=pin_id, added_by=pin.created_by)
    if created:
        pins_api.mark_confirmed(db, pin_id=pin_id, map_id=pin.map_id)
    return created


def unassign_outside_dates(db: Session, *, map_id: str, start_date, end_date) -> int:
    """Called with the map row locked when its travel dates change; caller commits."""
    return service.unassign_outside_dates(db, map_id=map_id, start_date=start_date, end_date=end_date)

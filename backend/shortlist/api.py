"""
다른 모듈이 shortlist를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 확정 개수 집계와, 핀 삭제 시 확정 항목 정리(#235)다.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from authz.core import Principal
from shortlist import flows, service
from shortlist.models import ShortlistItem


def count_confirmed(db: Session, *, map_id: str) -> int:
    """maps.for_Root.md 항목5(Map.confirmed_count)가 쓴다. shortlist_items는 상태 컬럼이
    없어 행 존재 자체가 확정이다(제외는 행을 지운다, service.py::remove_item) — list_items와
    같은 기준(map_id만)으로 센다. 소프트삭제된 핀의 행이 섞여 있어도 그대로 센다 —
    get_coordinates_for_pins가 동선 계산에서만 그런 행을 제외하는 것과는 별개 판단이다."""
    return db.execute(
        select(func.count()).select_from(ShortlistItem).where(ShortlistItem.map_id == map_id)
    ).scalar_one()


def remove_for_deleted_pin(db: Session, *, map_id: str, pin_id: str, principal: Principal) -> None:
    """핀을 삭제하기 **직전에** pins가 부른다(#235). 그 핀이 확정 리스트에 있으면 항목을 같은
    트랜잭션에서 지우고 shortlist.changed(removed)를 낸다 — 안 지우면 확정 리스트 조회가 삭제된
    핀 때문에 통째로 404가 되고 confirmed_count가 어긋난다. 핀이 아직 읽혀야 이벤트 페이로드(핀 응답)를
    만들 수 있어서 소프트 삭제보다 먼저 부른다. 확정 항목이 없으면 아무것도 하지 않는다.
    동선(route.recalculated)은 확정 리스트 변경만으로는 발행하지 않는다(docs/events.md) —
    일반 제외(DELETE /shortlist/{itemId})와 같은 규칙이다."""
    item_row = db.execute(
        select(ShortlistItem).where(ShortlistItem.map_id == map_id, ShortlistItem.pin_id == uuid.UUID(pin_id))
    ).scalar_one_or_none()
    if item_row is not None:
        flows.unconfirm_pin(db, item_row=item_row, principal=principal)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 shortlist_items·routes만 지우고 테이블 이름 →
    지운 행 수를 돌려준다. 핀(pins)보다 먼저 불러야 한다(shortlist_items.pin_id가 pins를 참조). 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)

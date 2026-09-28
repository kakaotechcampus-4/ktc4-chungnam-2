"""
다른 모듈이 shortlist를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 지금은 확정 개수 집계 하나뿐이다.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortlist.models import ShortlistItem


def count_confirmed(db: Session, *, map_id: str) -> int:
    """maps.for_Root.md 항목5(Map.confirmed_count)가 쓴다. shortlist_items는 상태 컬럼이
    없어 행 존재 자체가 확정이다(제외는 행을 지운다, service.py::remove_item) — list_items와
    같은 기준(map_id만)으로 센다. 소프트삭제된 핀의 행이 섞여 있어도 그대로 센다 —
    get_coordinates_for_pins가 동선 계산에서만 그런 행을 제외하는 것과는 별개 판단이다."""
    return db.execute(
        select(func.count()).select_from(ShortlistItem).where(ShortlistItem.map_id == map_id)
    ).scalar_one()

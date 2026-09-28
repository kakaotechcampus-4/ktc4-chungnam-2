"""
얇은 I/O 셸 — shortlist_items 테이블 CRUD만 한다(docs/code-quality.md). 분기·조립 로직은
shortlist/core.py로, pins 테이블을 건드리는 부분은 shortlist/flows.py(pins.api 경유)로 위임한다.
"""

import uuid

from sqlalchemy import BigInteger, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError
from shortlist.models import Route as RouteRow
from shortlist.models import ShortlistItem as ShortlistItemRow
from shortlist.schemas import Route


def _find_existing_item(db: Session, map_id: str, pin_id: str) -> ShortlistItemRow:
    return db.execute(
        select(ShortlistItemRow).where(
            ShortlistItemRow.map_id == map_id, ShortlistItemRow.pin_id == uuid.UUID(pin_id),
        )
    ).scalar_one()


def add_item(db: Session, *, map_id: str, pin_id: str, added_by: str) -> tuple[ShortlistItemRow, bool]:
    """unique(map_id, pin_id) 위반을 세이브포인트로 잡아 이미 있던 행을 돌려준다
    (pins.api.create_ai_pin과 같은 패턴 — db.rollback()을 begin_nested()와 함께 반드시 부른다,
    안 그러면 세션이 PendingRollbackError로 죽는다). 반환한 bool이 flows.confirm_pin의 멱등
    분기 기준이다 — False면 pins.kind 재변경도 이벤트도 건너뛴다."""
    row = ShortlistItemRow(map_id=map_id, pin_id=uuid.UUID(pin_id), added_by=added_by)
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        sqlstate = getattr(exc.orig, "pgcode", None)
        if sqlstate == "23505" and "uq_shortlist_map_pin" in str(exc.orig):
            return _find_existing_item(db, map_id, pin_id), False
        raise
    return row, True


def get_item_or_404(db: Session, item_id: str) -> ShortlistItemRow:
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    row = db.execute(select(ShortlistItemRow).where(ShortlistItemRow.id == item_uuid)).scalar_one_or_none()
    if row is None:
        raise AppError("NOT_FOUND")
    return row


def delete_item(db: Session, item_id: str) -> None:
    """core delete() 구문을 쓴다(pins/service.py::delete_reaction과 같은 이유) — ORM
    session.delete(row)와 달리 이미 읽어둔 row 인스턴스를 만료시키지 않는다."""
    db.execute(delete(ShortlistItemRow).where(ShortlistItemRow.id == uuid.UUID(item_id)))
    db.flush()


def list_items(db: Session, *, map_id: str) -> list[ShortlistItemRow]:
    return list(
        db.execute(
            select(ShortlistItemRow)
            .where(ShortlistItemRow.map_id == map_id)
            # added_at만으로는 동률(같은 트랜잭션에서 여러 핀을 연달아 확정하면 타임스탬프가
            # 같을 수 있다) 시 순서가 DB 스캔 순서에 맡겨져 매번 달라질 수 있다 — id를 2차
            # 정렬 기준으로 둬서 동선 계산(routing.compute_routes)의 구역 번호·투어 시작점이
            # 안정적이게 한다(Antigravity 검수 지적).
            .order_by(ShortlistItemRow.added_at, ShortlistItemRow.id)
        ).scalars()
    )


def replace_routes(db: Session, *, map_id: str, routes: list[Route]) -> list[RouteRow]:
    """POST /maps/{mapId}/route 계약대로 해당 map_id의 기존 행을 지우고 새로 쓴다 — 부분
    갱신은 없다(docs/data-model.md 100-108행). DELETE·INSERT를 같은 트랜잭션에서 실행해
    GET이 빈 배열을 보는 순간을 만들지 않는다(호출자인 shortlist/flows.py::recalculate_route가
    커밋 전까지 이 세션을 그대로 들고 있는다).

    같은 map_id에 대한 재계산 요청 두 개가 동시에 들어오면(더블 클릭, 두 구성원이 동시에 버튼을
    누름) DELETE와 INSERT가 경합해 uq_routes_map_region 유니크 제약을 위반할 수 있다(Antigravity
    검수 지적, 실제로 재현 가능한 경합임을 확인). 트랜잭션 범위 advisory lock으로 같은 map_id의
    재계산을 직렬화한다 — 커밋/롤백 시 자동 해제되므로 별도 unlock이 필요 없다."""
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(map_id).cast(BigInteger))))
    db.execute(delete(RouteRow).where(RouteRow.map_id == map_id))
    rows = [
        RouteRow(
            map_id=map_id,
            region_label=route.region_label,
            ordered_pin_ids=route.ordered_pin_ids,
            total_distance_m=route.total_distance_m,
            legs=[leg.model_dump() for leg in route.legs],
        )
        for route in routes
    ]
    db.add_all(rows)
    db.flush()
    return rows


def list_routes(db: Session, *, map_id: str) -> list[RouteRow]:
    # region_label("구역 N")로 정렬 — routing.compute_routes가 만드는 지역 수는 v1 실사용
    # 범위에서 한 자릿수를 벗어나지 않을 것으로 보고 문자열 정렬을 그대로 쓴다(구역 10 이상이면
    # "구역 10"이 "구역 2"보다 앞에 오는 사전식 정렬 함정이 있음 — for_Root.md에 남김).
    return list(
        db.execute(
            select(RouteRow).where(RouteRow.map_id == map_id).order_by(RouteRow.region_label)
        ).scalars()
    )

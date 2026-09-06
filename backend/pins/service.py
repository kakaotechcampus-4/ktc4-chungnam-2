"""
얇은 I/O 셸 — 입력 수집 → core 호출 → 출력 변환만 한다(docs/code-quality.md).
분기·계산 로직은 여기 두지 않고 pins/core.py로 위임한다.
"""

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pins import core
from pins.errors import PinError
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.ports import EventPublisher, MembershipGateway, PinDraft, PlaceGateway
from pins.schemas import Pin, PinCreateRequest


def _lat_lng_columns():
    """geom::geometry 캐스트 후 ST_X/ST_Y로 좌표를 뽑는다(geography 컬럼엔 ST_X/ST_Y가 직접 안 먹는다)."""
    geom_as_geometry = cast(PinRow.geom, Geometry())
    return func.ST_Y(geom_as_geometry).label("lat"), func.ST_X(geom_as_geometry).label("lng")


def list_pins(
    db: Session,
    map_id: str,
    viewer_id: str,
    membership: MembershipGateway,
    category: str | None = None,
    kind: str | None = None,
    created_by: list[str] | None = None,
) -> list[Pin]:
    lat_col, lng_col = _lat_lng_columns()

    reaction_counts = (
        select(
            ReactionRow.pin_id.label("pin_id"),
            func.count().filter(ReactionRow.type == "like").label("like"),
            func.count().filter(ReactionRow.type == "neutral").label("neutral"),
            func.count().filter(ReactionRow.type == "against").label("against"),
        )
        .group_by(ReactionRow.pin_id)
        .subquery()
    )

    query = (
        select(
            PinRow,
            lat_col,
            lng_col,
            func.coalesce(reaction_counts.c.like, 0).label("like_count"),
            func.coalesce(reaction_counts.c.neutral, 0).label("neutral_count"),
            func.coalesce(reaction_counts.c.against, 0).label("against_count"),
        )
        .outerjoin(reaction_counts, reaction_counts.c.pin_id == PinRow.id)
        .where(PinRow.map_id == map_id)
        .where(
            # 괄호를 명시한다 — AND가 OR보다 우선순위가 높아, 괄호 없이 이어붙이면
            # 삭제된(deleted_at NOT NULL) 남의 비공개 핀까지 새어나온다(가드레일 1).
            and_(
                PinRow.deleted_at.is_(None),
                or_(PinRow.visibility == "public", PinRow.created_by == viewer_id),
            )
        )
    )
    if category:
        query = query.where(PinRow.category == category)
    if kind:
        query = query.where(PinRow.kind == kind)
    if created_by:
        query = query.where(PinRow.created_by.in_(created_by))

    rows = db.execute(query).all()

    # 목록 전체에 대해 한 번만 확인한다 — 핀마다 부르지 않는다.
    is_member = membership.is_member(map_id, viewer_id)

    result: list[Pin] = []
    for row in rows:
        pin_row: PinRow = row[0]
        record = core.PinRecord(
            id=str(pin_row.id),
            map_id=pin_row.map_id,
            category=pin_row.category,
            kind=pin_row.kind,
            visibility=pin_row.visibility,
            lat=row.lat,
            lng=row.lng,
            created_by=pin_row.created_by,
            reaction_counts=core.ReactionCounts(
                like=row.like_count, neutral=row.neutral_count, against=row.against_count
            ),
        )
        result.append(core.to_pin_response(record, viewer_id, is_member))
    return result


def _find_existing_pin_id(db: Session, map_id: str, place_id: str) -> str | None:
    row = db.execute(
        select(PinRow.id).where(
            PinRow.map_id == map_id,
            PinRow.place_id == place_id,
            PinRow.deleted_at.is_(None),
        )
    ).first()
    return str(row[0]) if row else None


def create_pin(
    db: Session,
    map_id: str,
    viewer_id: str,
    req: PinCreateRequest,
    places: PlaceGateway,
    membership: MembershipGateway,
    publisher: EventPublisher,
) -> Pin:
    source = core.validate_create(req)

    resolved = places.resolve(
        PinDraft(
            source=source,
            link_url=req.link_url,
            place_id=req.place_id,
            lat=req.lat,
            lng=req.lng,
        )
    )

    existing_id = _find_existing_pin_id(db, map_id, resolved.place_id) if resolved.place_id else None
    existing_place_ids = {resolved.place_id} if existing_id is not None else set()
    if core.is_duplicate(existing_place_ids, resolved.place_id):
        raise PinError(409, "PIN_DUPLICATE", "이미 지도에 있는 장소입니다", detail={"pin_id": existing_id})

    pin_row = PinRow(
        map_id=map_id,
        category=req.category,
        kind="일반",
        origin="direct",
        place_id=resolved.place_id,
        geom=func.ST_SetSRID(func.ST_MakePoint(resolved.lng, resolved.lat), 4326),
        visibility="public",
        created_by=viewer_id,
    )
    db.add(pin_row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # 부분 유니크(uq_pins_map_place) 위반일 때만 409로 바꾼다 — 그 외 무결성 오류를
        # 조용히 삼키면 실패를 감추는 코드가 된다(docs/code-quality.md). psycopg2 예외의
        # pgcode가 SQLSTATE — 23505 = unique_violation.
        sqlstate = getattr(exc.orig, "pgcode", None)
        if sqlstate == "23505" and "uq_pins_map_place" in str(exc.orig):
            existing_id = _find_existing_pin_id(db, map_id, resolved.place_id)
            raise PinError(
                409, "PIN_DUPLICATE", "이미 지도에 있는 장소입니다", detail={"pin_id": existing_id}
            ) from exc
        raise

    lat_col, lng_col = _lat_lng_columns()
    lat, lng = db.execute(select(lat_col, lng_col).where(PinRow.id == pin_row.id)).one()

    record = core.PinRecord(
        id=str(pin_row.id),
        map_id=pin_row.map_id,
        category=pin_row.category,
        kind=pin_row.kind,
        visibility=pin_row.visibility,
        lat=lat,
        lng=lng,
        created_by=pin_row.created_by,
        reaction_counts=core.ReactionCounts(),
    )
    is_member = membership.is_member(map_id, viewer_id)
    pin = core.to_pin_response(record, viewer_id, is_member)

    db.commit()

    event = core.pin_created_event(pin)
    if event is not None:
        channel, event_type, payload = event
        publisher.publish(map_id, channel, event_type, payload)

    return pin


def delete_pin(
    db: Session,
    pin_id: str,
    viewer_id: str,
    membership: MembershipGateway,
    publisher: EventPublisher,
) -> None:
    try:
        pin_uuid = uuid.UUID(pin_id)
    except ValueError:
        raise PinError(404, "NOT_FOUND", "핀을 찾을 수 없습니다") from None

    pin_row = db.get(PinRow, pin_uuid)
    if pin_row is None or pin_row.deleted_at is not None:
        raise PinError(404, "NOT_FOUND", "핀을 찾을 수 없습니다")

    if not membership.is_member(pin_row.map_id, viewer_id):
        raise PinError(403, "FORBIDDEN", "이 지도의 구성원이 아닙니다")

    # soft delete — data-model.md의 부분 유니크(where deleted_at is null)가 이를 전제한다.
    pin_row.deleted_at = datetime.now(timezone.utc)
    db.commit()

    event = core.pin_deleted_event(str(pin_row.id), pin_row.visibility)
    if event is not None:
        channel, event_type, payload = event
        publisher.publish(pin_row.map_id, channel, event_type, payload)

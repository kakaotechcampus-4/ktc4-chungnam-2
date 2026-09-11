"""이 모듈의 함수는 전부 이미 인가된 리소스를 받는다는 전제다 — router.py가 authz.guard를
거쳐 넘겨준 PinRow/Principal만 인자로 받는다. 이 함수들을 가드 없이 직접 호출하는 새 코드를
추가하지 않는다(pins.api도 예외 아님 — 그쪽은 자기 나름의 authz 대신 "recommend/shortlist가
이미 authz.guard를 거친 뒤에만 부른다"는 자신의 전제를 갖는다, pins/api.py 참고).

얇은 I/O 셸 — 입력 수집 → core 호출 → 출력 변환만 한다(docs/code-quality.md).
분기·계산 로직은 여기 두지 않고 pins/core.py로 위임한다.
"""

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from authz.core import Principal
from common.errors import AppError
from common.events import record_event
from pins import core
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.ports import PinDraft, PlaceGateway
from pins.schemas import Pin, PinCreateRequest, Reaction, ReactionRequest, ReactionSummary


def _lat_lng_columns():
    """geom::geometry 캐스트 후 ST_X/ST_Y로 좌표를 뽑는다(geography 컬럼엔 ST_X/ST_Y가 직접 안 먹는다)."""
    geom_as_geometry = cast(PinRow.geom, Geometry())
    return func.ST_Y(geom_as_geometry).label("lat"), func.ST_X(geom_as_geometry).label("lng")


def get_pin_or_404(db: Session, pin_id: str) -> PinRow:
    """삭제되지 않은 핀을 id로 조회한다. 없으면 404 NOT_FOUND — 이 함수는 private 여부는
    보지 않는다(그건 존재 확인과 다른 질문이라 호출자가 따로 판단한다 — pins/loaders.py::load_pin,
    pins/api.py::get_pin_for_viewer)."""
    try:
        pin_uuid = uuid.UUID(pin_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    row = db.execute(
        select(PinRow).where(PinRow.id == pin_uuid, PinRow.deleted_at.is_(None))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("NOT_FOUND")
    return row


def list_pins(
    db: Session,
    map_id: str,
    principal: Principal,
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
                or_(PinRow.visibility == "public", PinRow.created_by == principal.user_id),
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
        result.append(core.to_pin_response(record, principal))
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
    principal: Principal,
    req: PinCreateRequest,
    places: PlaceGateway,
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
        raise AppError("PIN_DUPLICATE", detail={"pin_id": existing_id})

    pin_row = PinRow(
        map_id=map_id,
        category=req.category,
        kind="일반",
        origin="direct",
        place_id=resolved.place_id,
        geom=func.ST_SetSRID(func.ST_MakePoint(resolved.lng, resolved.lat), 4326),
        visibility="public",
        created_by=principal.user_id,
    )
    db.add(pin_row)
    try:
        with db.begin_nested():   # SAVEPOINT — 실패해도 바깥 트랜잭션은 살아 있다
            db.flush()
    except IntegrityError as exc:
        # begin_nested()가 SAVEPOINT까지는 롤백해도 Session 자체는 "deactive" 상태로 남는다 —
        # 실제 PostgreSQL로 직접 확인함(세이브포인트만으론 이후 쿼리가 PendingRollbackError로
        # 죽는다). db.rollback()을 명시적으로 불러야 세션이 다시 쓸 수 있는 상태가 되고,
        # 이전에 커밋된 데이터는 그대로 남는다(같은 방식으로 검증). 원래(#16) 코드의
        # db.rollback()을 지우지 않고 begin_nested()와 함께 쓴다.
        db.rollback()
        # 부분 유니크(uq_pins_map_place) 위반일 때만 409로 바꾼다 — 그 외 무결성 오류를
        # 조용히 삼키면 실패를 감추는 코드가 된다(docs/code-quality.md). psycopg2 예외의
        # pgcode가 SQLSTATE — 23505 = unique_violation.
        sqlstate = getattr(exc.orig, "pgcode", None)
        if sqlstate == "23505" and "uq_pins_map_place" in str(exc.orig):
            existing_id = _find_existing_pin_id(db, map_id, resolved.place_id)
            raise AppError("PIN_DUPLICATE", detail={"pin_id": existing_id}) from exc
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
    pin = core.to_pin_response(record, principal)

    record_event(db, core.pin_created_event(pin))

    return pin


def delete_pin(db: Session, pin: PinRow) -> None:
    # soft delete — data-model.md의 부분 유니크(where deleted_at is null)가 이를 전제한다.
    pin.deleted_at = datetime.now(timezone.utc)
    db.flush()

    record_event(db, core.pin_deleted_event(str(pin.id), pin.map_id, pin.visibility))


def _reaction_counts_for_pin(db: Session, pin_id: uuid.UUID) -> core.ReactionCounts:
    row = db.execute(
        select(
            func.count().filter(ReactionRow.type == "like").label("like"),
            func.count().filter(ReactionRow.type == "neutral").label("neutral"),
            func.count().filter(ReactionRow.type == "against").label("against"),
        ).where(ReactionRow.pin_id == pin_id)
    ).one()
    return core.ReactionCounts(like=row.like, neutral=row.neutral, against=row.against)


def set_reaction(db: Session, pin: PinRow, viewer_id: str, req: ReactionRequest) -> Reaction:
    core.validate_reaction(req.type, req.reason_text, req.reason_chip_ids)
    reason_text = (req.reason_text or "").strip() or None

    # 원자적 upsert — 조회 후 있으면 UPDATE 없으면 INSERT(check-then-act) 방식은 같은 유저가
    # 동시에 두 번 PUT을 보내면 유니크 제약(uq_reactions_pin_user) 위반 레이스가 날 수 있다.
    stmt = pg_insert(ReactionRow).values(
        pin_id=pin.id,
        user_id=viewer_id,
        type=req.type,
        reason_text=reason_text,
        reason_chip_ids=req.reason_chip_ids,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["pin_id", "user_id"],
        set_={
            "type": stmt.excluded.type,
            "reason_text": stmt.excluded.reason_text,
            "reason_chip_ids": stmt.excluded.reason_chip_ids,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)

    counts = _reaction_counts_for_pin(db, pin.id)
    summary = ReactionSummary(like=counts.like, neutral=counts.neutral, against=counts.against)
    record_event(db, core.reaction_changed_event(str(pin.id), pin.map_id, pin.visibility, summary))

    return Reaction(pin_id=str(pin.id), user_id=viewer_id, type=req.type, reason_text=reason_text)


def delete_reaction(db: Session, pin: PinRow, viewer_id: str) -> None:
    result = db.execute(
        delete(ReactionRow).where(ReactionRow.pin_id == pin.id, ReactionRow.user_id == viewer_id)
    )
    deleted = result.rowcount > 0

    # 실제로 뭔가 지워졌을 때만 발행한다 — 반응이 원래 없던 핀에 DELETE를 보내도 204는
    # 똑같이 나가지만(idempotent), 상태 변화가 없으므로 이벤트로 SSE를 스팸하지 않는다.
    if not deleted:
        return

    counts = _reaction_counts_for_pin(db, pin.id)
    summary = ReactionSummary(like=counts.like, neutral=counts.neutral, against=counts.against)
    record_event(db, core.reaction_changed_event(str(pin.id), pin.map_id, pin.visibility, summary))

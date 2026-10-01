"""이 모듈의 함수는 전부 이미 인가된 리소스를 받는다는 전제다 — router.py가 authz.guard를
거쳐 넘겨준 PinRow/Principal만 인자로 받는다. 이 함수들을 가드 없이 직접 호출하는 새 코드를
추가하지 않는다(pins.api도 예외 아님 — 그쪽은 자기 나름의 authz 대신 "recommend/shortlist가
이미 authz.guard를 거친 뒤에만 부른다"는 자신의 전제를 갖는다, pins/api.py 참고).

얇은 I/O 셸 — 입력 수집 → core 호출 → 출력 변환만 한다(docs/code-quality.md).
분기·계산 로직은 여기 두지 않고 pins/core.py로 위임한다.
"""

import uuid
from datetime import datetime, timezone
from typing import get_args

from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import api as auth_api
from places import api as places_api
from places.schemas import PlaceHint, PlaceInfo
from authz.core import Principal
from common.errors import AppError
from common.events import record_event
from pins import core
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.schemas import (
    Category,
    FilterCounts,
    Pin,
    PinCreateRequest,
    PinKind,
    Reaction,
    ReactionRequest,
    ReactionSummary,
)


def _lat_lng_columns():
    """geom::geometry 캐스트 후 ST_X/ST_Y로 좌표를 뽑는다(geography 컬럼엔 ST_X/ST_Y가 직접 안 먹는다)."""
    geom_as_geometry = cast(PinRow.geom, Geometry())
    return func.ST_Y(geom_as_geometry).label("lat"), func.ST_X(geom_as_geometry).label("lng")


def _visible_pins_clause(map_id: str, viewer_id: str):
    """그 지도에서 viewer에게 보이는 핀의 단일 판정 — list_pins와 count_pins가 같이 쓴다
    (목록과 집계가 어긋나면 비공개 후보 개수가 새거나 배지 숫자가 목록과 달라진다, 가드레일 1).
    괄호를 명시한다 — AND가 OR보다 우선순위가 높아, 괄호 없이 이어붙이면 삭제된
    (deleted_at NOT NULL) 남의 비공개 핀까지 새어나온다."""
    return and_(
        PinRow.map_id == map_id,
        PinRow.deleted_at.is_(None),
        or_(PinRow.visibility == "public", PinRow.created_by == viewer_id),
    )


def count_pins(db: Session, map_id: str, principal: Principal) -> FilterCounts:
    """분류×종류 집계(#141) — 보이는 핀만 GROUP BY 한 번으로 센다. 핀이 없는 카테고리·종류도
    0으로 채운다. 키는 스키마 Literal에서 만든다(「기타」가 추가돼도 여기를 안 고친다)."""
    by_category = {c: 0 for c in get_args(Category)}
    by_kind = {k: 0 for k in get_args(PinKind)}
    rows = db.execute(
        select(PinRow.category, PinRow.kind, func.count())
        .where(_visible_pins_clause(map_id, principal.user_id))
        .group_by(PinRow.category, PinRow.kind)
    ).all()
    for category, kind, n in rows:
        by_category[category] += n
        by_kind[kind] += n
    return FilterCounts(by_category=by_category, by_kind=by_kind)


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
        .where(_visible_pins_clause(map_id, principal.user_id))
    )
    if category:
        query = query.where(PinRow.category == category)
    if kind:
        query = query.where(PinRow.kind == kind)
    if created_by:
        query = query.where(PinRow.created_by.in_(created_by))

    rows = db.execute(query).all()

    # 배치 조회 — N개 핀에 N번 쿼리하지 않는다(auth.api.display_names 자체가 배치용으로 설계됨).
    display_names = auth_api.display_names(db, [row[0].created_by for row in rows])
    my_reactions = my_reactions_for_pins(db, [row[0].id for row in rows], principal.user_id)
    place_infos = places_api.get_places([row[0].place_id for row in rows], db=db)   # 배치 1회

    result: list[Pin] = []
    for row in rows:
        pin_row: PinRow = row[0]
        record = record_from_row(
            pin_row,
            lat=row.lat,
            lng=row.lng,
            reaction_counts=core.ReactionCounts(
                like=row.like_count, neutral=row.neutral_count, against=row.against_count
            ),
            created_by_display_name=display_names.get(pin_row.created_by),
            my_reaction=my_reactions.get(pin_row.id),
            place=place_infos.get(pin_row.place_id),
        )
        result.append(core.to_pin_response(record, principal))
    return result


def record_from_row(
    pin_row: PinRow,
    *,
    lat: float,
    lng: float,
    reaction_counts: core.ReactionCounts,
    created_by_display_name: str | None,
    my_reaction: Reaction | None,
    place: PlaceInfo | None,
) -> core.PinRecord:
    """ORM 행 → 응답 조립용 PinRecord. 목록·단건(api.get_pin_response_for_viewer)이 같은 필드를
    싣도록 한 곳에 둔다 — 필드가 늘 때 한쪽만 빠지는 걸 막는다."""
    return core.PinRecord(
        id=str(pin_row.id),
        map_id=pin_row.map_id,
        category=pin_row.category,
        kind=pin_row.kind,
        visibility=pin_row.visibility,
        lat=lat,
        lng=lng,
        created_by=pin_row.created_by,
        reaction_counts=reaction_counts,
        place_name=place.name if place else None,
        place_url=place.kakao_place_url if place else None,
        created_by_display_name=created_by_display_name,
        checks=pin_row.checks,
        reason=pin_row.reason,
        member_fulfillment=pin_row.member_fulfillment,
        place_source=pin_row.place_source,
        my_reaction=my_reaction,
    )


def _reaction_from_row(row: ReactionRow, display_name: str | None = None) -> Reaction:
    return Reaction(
        pin_id=str(row.pin_id),
        user_id=row.user_id,
        type=row.type,
        reason_text=row.reason_text,
        reason_chip_ids=row.reason_chip_ids,
        display_name=display_name,
    )


def my_reactions_for_pins(db: Session, pin_ids: list[uuid.UUID], viewer_id: str) -> dict[uuid.UUID, Reaction]:
    """요청자 본인의 반응을 핀 id 배치로 한 번에 조회한다(N+1 금지). 반응 없는 핀은 키가 없다."""
    if not pin_ids:
        return {}
    rows = db.execute(
        select(ReactionRow).where(ReactionRow.pin_id.in_(pin_ids), ReactionRow.user_id == viewer_id)
    ).scalars().all()
    return {row.pin_id: _reaction_from_row(row) for row in rows}


def list_reactions(db: Session, pin: PinRow) -> list[Reaction]:
    """GET /pins/{pinId}/reactions — 반응한 구성원만(미응답자는 포함하지 않는다). 숙소 핀은 빈
    배열(반응 행이 생기지 않는 카테고리, permissions.md). 오래된 순으로 안정 정렬한다."""
    if pin.category == "숙소":
        return []
    rows = db.execute(
        select(ReactionRow).where(ReactionRow.pin_id == pin.id).order_by(ReactionRow.created_at, ReactionRow.user_id)
    ).scalars().all()
    names = auth_api.display_names(db, [row.user_id for row in rows])
    return [_reaction_from_row(row, names.get(row.user_id)) for row in rows]


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
) -> Pin:
    """검색 결과를 골라 핀을 만든다(#195). 요청의 place_id·place_name·lat·lng는 같은 자체 DB 장소를 찾는
    힌트일 뿐 저장하지 않는다 — 핀의 장소·좌표는 매칭된 places 행에서 온다."""
    core.validate_create(req)

    match = places_api.match_place(
        PlaceHint(kakao_place_id=req.place_id, name=req.place_name, lat=req.lat, lng=req.lng, category=req.category),
        db=db,
    )
    if match is None:
        raise AppError("PLACE_NOT_SUPPORTED")
    core.validate_category_matches(req.category, match.category)

    existing_id = _find_existing_pin_id(db, map_id, match.place_id)
    existing_place_ids = {match.place_id} if existing_id is not None else set()
    if core.is_duplicate(existing_place_ids, match.place_id):
        raise AppError("PIN_DUPLICATE", detail={"pin_id": existing_id})

    pin_row = PinRow(
        map_id=map_id,
        category=req.category,
        kind="일반",
        origin="direct",
        place_id=match.place_id,
        geom=func.ST_SetSRID(func.ST_MakePoint(match.lng, match.lat), 4326),
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
            existing_id = _find_existing_pin_id(db, map_id, match.place_id)
            raise AppError("PIN_DUPLICATE", detail={"pin_id": existing_id}) from exc
        raise

    # 핀이 만들어진 뒤에만 카카오 ID·URL을 기록한다(같은 트랜잭션) — 중복·실패한 요청이 자체 DB를 건드리지 않게.
    kakao_url = core.kakao_place_url(req.place_id)
    if kakao_url is not None:
        places_api.record_kakao_match(match.place_id, req.place_id, kakao_url, db=db)

    lat_col, lng_col = _lat_lng_columns()
    lat, lng = db.execute(select(lat_col, lng_col).where(PinRow.id == pin_row.id)).one()
    place = places_api.get_places([match.place_id], db=db).get(match.place_id)

    display_name = auth_api.display_names(db, [pin_row.created_by]).get(pin_row.created_by)
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
        place_name=place.name if place else match.name,
        place_url=place.kakao_place_url if place else None,
        created_by_display_name=display_name,
    )
    pin = core.to_pin_response(record, principal)

    record_event(db, core.pin_created_event(pin))

    return pin


def delete_pin(db: Session, pin: PinRow) -> None:
    # 조건부 UPDATE — "확인 후 처리"(check-then-act, pin.deleted_at = ...; db.flush())는
    # 동시 삭제 요청 두 개가 둘 다 loader를 통과한 뒤 둘 다 UPDATE에 성공해 pin.deleted
    # 이벤트가 두 번 발행될 수 있다(#51 — realtime이 실제로 이벤트를 전송하므로 더 이상
    # 무시할 수 있는 문제가 아니다). WHERE에 deleted_at IS NULL을 넣어 DB 레벨에서 원자적으로
    # 처리하고, rowcount로 "내가 실제로 처음 지운 것"인지 판단한다(soft delete — data-model.md의
    # 부분 유니크가 이를 전제한다).
    result = db.execute(
        update(PinRow)
        .where(PinRow.id == pin.id, PinRow.deleted_at.is_(None))
        .values(deleted_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        # 이미 다른 요청이 먼저 지웠다 — 상태 변화가 없으므로 이벤트를 또 쏘지 않는다
        # (delete_reaction의 "실제로 지워졌을 때만 발행" 패턴과 동일한 원칙).
        return

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
    core.validate_reactable(pin.category)
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

    return Reaction(
        pin_id=str(pin.id), user_id=viewer_id, type=req.type,
        reason_text=reason_text, reason_chip_ids=req.reason_chip_ids,
    )


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

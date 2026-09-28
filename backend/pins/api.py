"""
다른 모듈이 pins를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). recommend(후보 게시)·shortlist(핀 확정)가 착수하면 이 파일을
통해서만 pins 테이블을 건드린다.

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다.
db.flush()만으로 PK/유니크 충돌 등은 여전히 그 자리에서 드러난다.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from authz.core import Principal
from common.errors import AppError
from common.events import Event
from pins import core, service
from pins.models import Pin as PinRow
from pins.schemas import Pin


@dataclass(frozen=True)
class PinMutation:
    pin: PinRow           # 호출자가 응답 조립에 쓸 수 있는 값
    event: Event | None    # 호출자가 record_event로 같은 커밋에 넣는다(호출자 책임)


def create_ai_pin(
    db: Session, *, map_id: str, category: str, place_id: str, lat: float, lng: float, created_by: str,
) -> PinMutation:
    """recommend의 후보 게시 전용. kind='AI추천', origin='ai', visibility='public'.
    place_id 중복이면 AppError('PIN_DUPLICATE') — 누가 이미 그 장소를 직접 찍었다는 뜻이다.
    v1은 private pins 행을 만들지 않으므로(recommend 계획 참고) 이 함수는 항상 public으로
    바로 INSERT한다 — visibility 전환 로직이 없다.

    permissions 계산에 쓸 Principal이 없어(호출자가 아직 없다) 게시자 본인을 map의 member로
    간주해 구성한다 — 게시(recommend.publish)는 이미 member 액션이라 이 전제가 깨질 일이 없다.
    recommend가 실제로 붙을 때 자신이 이미 resolve한 Principal을 넘기도록 바꾸는 편이 더
    정확하다(for_Root.md에 남김)."""
    principal = Principal(user_id=created_by, map_id=map_id, role="member")

    pin_row = PinRow(
        map_id=map_id, category=category, kind="AI추천", origin="ai",
        place_id=place_id,
        # service.py의 create_pin과 동일한 조립 방식(func.ST_SetSRID(func.ST_MakePoint(lng, lat), ...)).
        geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        visibility="public", created_by=created_by,
    )
    db.add(pin_row)
    try:
        with db.begin_nested():   # 방어 코드 2 재사용 — 세이브포인트 안에서만 flush
            db.flush()
    except IntegrityError as exc:
        # begin_nested()만으론 Session이 "deactive" 상태로 남아 이후 쿼리가 죽는다 — 실제
        # PostgreSQL로 확인함(pins/service.py::create_pin과 동일한 이유, 그쪽 주석 참고).
        db.rollback()
        sqlstate = getattr(exc.orig, "pgcode", None)
        if sqlstate == "23505" and "uq_pins_map_place" in str(exc.orig):
            existing_id = service._find_existing_pin_id(db, map_id, place_id)  # 기존 헬퍼 재사용
            raise AppError("PIN_DUPLICATE", detail={"pin_id": existing_id}) from exc
        raise

    record = core.PinRecord(
        id=str(pin_row.id), map_id=map_id, category=category, kind="AI추천",
        visibility="public", lat=lat, lng=lng, created_by=created_by,
        reaction_counts=core.ReactionCounts(),
    )
    pin = core.to_pin_response(record, principal)
    event = core.pin_created_event(pin)
    return PinMutation(pin=pin_row, event=event)


def mark_confirmed(db: Session, *, pin_id: str, map_id: str) -> PinMutation:
    """docs/data-model.md — kind를 바꾸는 유일한 경로. shortlist만 부른다."""
    pin_row = service.get_pin_or_404(db, pin_id)
    if pin_row.map_id != map_id:
        raise AppError("NOT_FOUND")   # authz Rule B와 같은 원칙 — 교차 지도 참조는 404
    pin_row.kind = "확정"
    db.flush()
    return PinMutation(pin=pin_row, event=None)   # shortlist.changed는 shortlist가 직접 기록


def unmark_confirmed(db: Session, *, pin_id: str, map_id: str) -> PinMutation:
    """kind를 origin에서 되돌린다 — core.kind_after_unconfirm(origin)."""
    pin_row = service.get_pin_or_404(db, pin_id)
    if pin_row.map_id != map_id:
        raise AppError("NOT_FOUND")
    pin_row.kind = core.kind_after_unconfirm(pin_row.origin)
    db.flush()
    return PinMutation(pin=pin_row, event=None)


def get_pin_for_viewer(db: Session, *, pin_id: str, viewer_id: str) -> PinRow:
    """존재·가시성 확인. 없으면 404 NOT_FOUND, 남의 private 핀은 404 AI_PIN_PRIVATE
    (둘 다 404라 호출자 입장에서 구분할 필요가 없다 — 존재를 흘리지 않는다는 원칙은 동일)."""
    pin_row = service.get_pin_or_404(db, pin_id)
    if pin_row.visibility == "private" and pin_row.created_by != viewer_id:
        raise AppError("AI_PIN_PRIVATE")
    return pin_row


def get_pin_response_for_viewer(db: Session, *, pin_id: str, viewer_id: str, principal: Principal) -> Pin:
    """shortlist(ShortlistItem.pin 조립)가 쓰는 완성형 핀 조회 — get_pin_for_viewer와 같은
    존재·가시성 규칙 위에 lat/lng·반응 집계·permissions까지 채운다. 다른 모듈이 pins·reactions
    테이블을 직접 쿼리하지 않고도 목록 화면(service.list_pins)과 같은 모양의 Pin을 받는다 —
    pins/service.py의 비공개 헬퍼(_lat_lng_columns·_reaction_counts_for_pin)를 같은 모듈
    안에서만 재사용한다."""
    pin_row = get_pin_for_viewer(db, pin_id=pin_id, viewer_id=viewer_id)
    lat_col, lng_col = service._lat_lng_columns()
    lat, lng = db.execute(select(lat_col, lng_col).where(PinRow.id == pin_row.id)).one()
    reaction_counts = service._reaction_counts_for_pin(db, pin_row.id)
    record = core.PinRecord(
        id=str(pin_row.id), map_id=pin_row.map_id, category=pin_row.category, kind=pin_row.kind,
        visibility=pin_row.visibility, lat=lat, lng=lng, created_by=pin_row.created_by,
        reaction_counts=reaction_counts,
    )
    return core.to_pin_response(record, principal)


def get_coordinates_for_pins(db: Session, pin_ids: list[str]) -> dict[str, tuple[float, float]]:
    """좌표만 필요한 벌크 조회 — shortlist의 동선 계산(5-10, #103)이 쓴다. 가시성 판정은 하지
    않는다: 확정 리스트(shortlist_items)에 들어간 핀은 가드레일 1(`shortlist/loaders.py::
    load_pin_for_confirm`)로 항상 visibility=public이므로 호출자가 이미 공개 핀 id만 넘긴다는
    전제다. 소프트 삭제된 핀(`deleted_at` not null)은 다른 모든 조회 함수와 같은 원칙으로
    제외한다(Antigravity 검수 지적 — 이전엔 이 함수만 필터가 빠져서 삭제된 핀이 동선에 남을 수
    있었다). 존재하지 않거나 삭제된 id는 결과 dict에서 조용히 빠진다(호출자가 필요하면 직접
    검사 — `shortlist/flows.py::recalculate_route`는 빠진 id를 건너뛴다)."""
    if not pin_ids:
        return {}
    uuids = [uuid.UUID(pid) for pid in pin_ids]
    lat_col, lng_col = service._lat_lng_columns()
    rows = db.execute(
        select(PinRow.id, lat_col, lng_col).where(PinRow.id.in_(uuids), PinRow.deleted_at.is_(None))
    ).all()
    return {str(pin_id): (lat, lng) for pin_id, lat, lng in rows}

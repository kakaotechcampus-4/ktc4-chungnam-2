"""
다른 모듈이 pins를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). recommend(후보 게시)·shortlist(핀 확정)가 착수하면 이 파일을
통해서만 pins 테이블을 건드린다.

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다.
db.flush()만으로 PK/유니크 충돌 등은 여전히 그 자리에서 드러난다.
"""

import uuid
from dataclasses import dataclass

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import api as auth_api
from authz.core import Principal
from common.errors import AppError
from common.events import Event
from pins import core, service
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.schemas import Check, Pin

_ChecksAdapter = TypeAdapter(list[Check])


@dataclass(frozen=True)
class PinMutation:
    pin: PinRow           # 호출자가 응답 조립에 쓸 수 있는 값
    event: Event | None    # 호출자가 record_event로 같은 커밋에 넣는다(호출자 책임)


def create_ai_pin(
    db: Session, *, map_id: str, category: str, place_id: str, lat: float, lng: float, created_by: str,
    checks: list[dict] | None = None,
) -> PinMutation:
    """recommend의 후보 게시 전용. kind='AI추천', origin='ai', visibility='public'.
    place_id 중복이면 AppError('PIN_DUPLICATE') — 누가 이미 그 장소를 직접 찍었다는 뜻이다.
    v1은 private pins 행을 만들지 않으므로(recommend 계획 참고) 이 함수는 항상 public으로
    바로 INSERT한다 — visibility 전환 로직이 없다.

    checks: #57/#124 결정 — candidate.checks를 게시 시점에 pins로 복사한다(가드레일 5, 게시
    후에도 조건별 충족 체크가 유지돼야 함). recommend가 나중에 candidate/run을 지우거나 바꿔도
    이 값은 안 바뀐다. 모양이 pins.schemas.Check와 안 맞으면 INSERT 전에 ValidationError로
    바로 실패한다(경계에서 검증) — recommend가 잘못된 페이로드를 그대로 밀어넣는 걸 막는다.

    permissions 계산에 쓸 Principal이 없어(호출자가 아직 없다) 게시자 본인을 map의 member로
    간주해 구성한다 — 게시(recommend.publish)는 이미 member 액션이라 이 전제가 깨질 일이 없다.
    recommend가 실제로 붙을 때 자신이 이미 resolve한 Principal을 넘기도록 바꾸는 편이 더
    정확하다(for_Root.md에 남김)."""
    principal = Principal(user_id=created_by, map_id=map_id, role="member")
    validated_checks = (
        [check.model_dump() for check in _ChecksAdapter.validate_python(checks)]
        if checks is not None else None
    )

    pin_row = PinRow(
        map_id=map_id, category=category, kind="AI추천", origin="ai",
        place_id=place_id,
        # service.py의 create_pin과 동일한 조립 방식(func.ST_SetSRID(func.ST_MakePoint(lng, lat), ...)).
        geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        visibility="public", created_by=created_by, checks=validated_checks,
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

    display_name = auth_api.display_names(db, [created_by]).get(created_by)
    record = core.PinRecord(
        id=str(pin_row.id), map_id=map_id, category=category, kind="AI추천",
        visibility="public", lat=lat, lng=lng, created_by=created_by,
        reaction_counts=core.ReactionCounts(),
        created_by_display_name=display_name,
        checks=validated_checks,
    )
    pin = core.to_pin_response(record, principal)
    # pin.published다 — docs/events.md가 "지도에 올리기"의 타입을 이렇게 못박아뒀고, 이 함수
    # 자신의 docstring도 "recommend의 후보 게시 전용"이라고 밝히고 있다. pin.created를 쓰면
    # recommend가 매번 type만 고쳐 새 Event를 만드는 우회가 필요해진다(recommend/flows.py에
    # 남아있던 것 — 이 수정으로 그 우회를 지웠다).
    event = core.pin_published_event(pin)
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
    display_name = auth_api.display_names(db, [pin_row.created_by]).get(pin_row.created_by)
    record = core.PinRecord(
        id=str(pin_row.id), map_id=pin_row.map_id, category=pin_row.category, kind=pin_row.kind,
        visibility=pin_row.visibility, lat=lat, lng=lng, created_by=pin_row.created_by,
        reaction_counts=reaction_counts, place_name=pin_row.place_name,
        created_by_display_name=display_name, checks=pin_row.checks,
    )
    return core.to_pin_response(record, principal)


def count_reacted_users(db: Session, *, map_id: str, category: str) -> int:
    """recommend readiness(5-4, recommend/#108)가 "카테고리별 의견 남긴 핀" 판정에 쓴다 —
    그 카테고리의 삭제되지 않은 핀 중 하나 이상에 반응(♥/△/🚫, '?' 미확인은 행 없음이라
    여기 안 잡힌다)을 남긴 서로 다른 user_id 수. shortlist를 위해 get_coordinates_for_pins를
    추가한 것과 같은 선례로 여기 추가한다."""
    return db.execute(
        select(func.count(func.distinct(ReactionRow.user_id)))
        .select_from(ReactionRow)
        .join(PinRow, PinRow.id == ReactionRow.pin_id)
        .where(PinRow.map_id == map_id, PinRow.category == category, PinRow.deleted_at.is_(None))
    ).scalar_one()


def get_category_pin_coordinates(db: Session, *, map_id: str, category: str) -> list[tuple[str, float, float]]:
    """recommend의 지역(regions) 기본값 계산(5-6-1, recommend/#108)이 쓴다 — 그 카테고리의
    삭제되지 않은 공개 핀 좌표 전부(anchor 후보). place_facts/PlaceSource가 아직 없어 recommend가
    "검색 범위 중심"을 스스로 정할 방법이 이것뿐이다(recommend/for_Root.md에 이 기본값 원
    설계를 상세히 기록)."""
    lat_col, lng_col = service._lat_lng_columns()
    rows = db.execute(
        select(PinRow.id, lat_col, lng_col).where(
            PinRow.map_id == map_id, PinRow.category == category,
            PinRow.visibility == "public", PinRow.deleted_at.is_(None),
        )
    ).all()
    return [(str(pin_id), lat, lng) for pin_id, lat, lng in rows]


def list_place_ids_on_map(db: Session, *, map_id: str) -> set[str]:
    """recommend의 후보 검색(#108)이 쓴다 — `unique(map_id, place_id) where deleted_at is null`
    제약(카테고리 무관, 지도 전체)과 정확히 같은 범위로 조회한다. 이 목록에 없는 place_id만
    후보로 남겨야 게시(`pins_api.create_ai_pin`) 시 PIN_DUPLICATE 409가 나지 않는다 — 이전엔
    `exclusions`(제안·거절 이력)만 걸러서, 이미 지도에 있는 핀(수동이든 이전 게시든)이 그대로
    다시 추천될 수 있었다(루트 수정, 2026-09-23 — Antigravity 검수로 발견)."""
    rows = db.execute(
        select(PinRow.place_id).where(PinRow.map_id == map_id, PinRow.deleted_at.is_(None))
    ).scalars().all()
    return set(rows)


def list_reasoned_reactions(db: Session, *, map_id: str, category: str) -> list[dict]:
    """recommend의 근거 조립(①②, recommend/#108)이 쓴다 — 그 카테고리 핀에 남긴 반응 중
    사유가 있는 것만(반대는 사유 필수라 가드레일3로 항상 있고, 좋음/조율 필요도 사유가 있으면
    포함한다). llm.service.plan_evidence에 넘길 raw_reasons의 원자료다."""
    rows = db.execute(
        select(
            ReactionRow.pin_id, ReactionRow.user_id, ReactionRow.type,
            ReactionRow.reason_text, ReactionRow.reason_chip_ids,
        )
        .select_from(ReactionRow)
        .join(PinRow, PinRow.id == ReactionRow.pin_id)
        .where(
            PinRow.map_id == map_id, PinRow.category == category, PinRow.deleted_at.is_(None),
            ReactionRow.reason_text.is_not(None),
        )
    ).all()
    return [
        {
            "pin_id": str(pin_id), "user_id": user_id, "type": reaction_type,
            "reason_text": reason_text, "reason_chip_ids": reason_chip_ids,
        }
        for pin_id, user_id, reaction_type, reason_text, reason_chip_ids in rows
    ]


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

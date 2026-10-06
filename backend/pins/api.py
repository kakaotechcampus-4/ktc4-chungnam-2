"""
다른 모듈이 pins를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). recommend(후보 게시)·shortlist(핀 확정)가 착수하면 이 파일을
통해서만 pins 테이블을 건드린다.

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다.
db.flush()만으로 PK/유니크 충돌 등은 여전히 그 자리에서 드러난다.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import api as auth_api
from places import api as places_api
from authz.core import Principal
from common.errors import AppError
from common.events import Event
from pins import chips, core, service
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow
from pins.schemas import Check, MemberFulfillment, Pin, PlaceSource

_ChecksAdapter = TypeAdapter(list[Check])


@dataclass(frozen=True)
class PinMutation:
    pin: PinRow           # 호출자가 응답 조립에 쓸 수 있는 값
    event: Event | None    # 호출자가 record_event로 같은 커밋에 넣는다(호출자 책임)


def create_ai_pin(
    db: Session, *, map_id: str, category: str, place_id: str, lat: float, lng: float, created_by: str,
    checks: list[dict] | None = None,
    reason: str | None = None, member_fulfillment: dict | None = None, place_source: dict | None = None,
) -> PinMutation:
    """recommend의 후보 게시 전용. kind='AI추천', origin='ai', visibility='public'.
    place_id 중복이면 AppError('PIN_DUPLICATE') — 누가 이미 그 장소를 직접 찍었다는 뜻이다.
    v1은 private pins 행을 만들지 않으므로(recommend 계획 참고) 이 함수는 항상 public으로
    바로 INSERT한다 — visibility 전환 로직이 없다.

    checks: #57/#124 결정 — candidate.checks를 게시 시점에 pins로 복사한다(가드레일 5, 게시
    후에도 조건별 충족 체크가 유지돼야 함). recommend가 나중에 candidate/run을 지우거나 바꿔도
    이 값은 안 바뀐다. 모양이 pins.schemas.Check와 안 맞으면 INSERT 전에 ValidationError로
    바로 실패한다(경계에서 검증) — recommend가 잘못된 페이로드를 그대로 밀어넣는 걸 막는다.

    reason/member_fulfillment/place_source(#157): checks와 같은 방식으로 candidate 값을 1회 복사한다
    (가드레일 5). 값은 recommend가 채우므로 모두 선택이고, 모양은 스키마(MemberFulfillment·
    PlaceSource)로 INSERT 전에 검증한다. 없으면 NULL.

    permissions 계산에 쓸 Principal이 없어(호출자가 아직 없다) 게시자 본인을 map의 member로
    간주해 구성한다 — 게시(recommend.publish)는 이미 member 액션이라 이 전제가 깨질 일이 없다.
    recommend가 실제로 붙을 때 자신이 이미 resolve한 Principal을 넘기도록 바꾸는 편이 더
    정확하다(for_Root.md에 남김)."""
    principal = Principal(user_id=created_by, map_id=map_id, role="member")
    validated_checks = (
        [check.model_dump() for check in _ChecksAdapter.validate_python(checks)]
        if checks is not None else None
    )
    validated_fulfillment = (
        MemberFulfillment.model_validate(member_fulfillment).model_dump(exclude_none=True)
        if member_fulfillment is not None else None
    )
    validated_source = (
        PlaceSource.model_validate(place_source).model_dump(exclude_none=True)
        if place_source is not None else None
    )

    pin_row = PinRow(
        map_id=map_id, category=category, kind="AI추천", origin="ai",
        place_id=place_id,
        # service.py의 create_pin과 동일한 조립 방식(func.ST_SetSRID(func.ST_MakePoint(lng, lat), ...)).
        geom=func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        visibility="public", created_by=created_by, checks=validated_checks,
        reason=reason, member_fulfillment=validated_fulfillment, place_source=validated_source,
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
    place = places_api.get_places([place_id], db=db).get(place_id)
    record = core.PinRecord(
        id=str(pin_row.id), map_id=map_id, category=category, kind="AI추천",
        visibility="public", lat=lat, lng=lng, created_by=created_by,
        reaction_counts=core.ReactionCounts(),
        place_name=place.name if place else None,
        place_url=place.kakao_place_url if place else None,
        created_by_display_name=display_name,
        created_at=pin_row.created_at,
        checks=validated_checks,
        reason=reason, member_fulfillment=validated_fulfillment, place_source=validated_source,
    )
    pin = core.to_pin_response(record, principal)
    # pin.published다 — docs/events.md가 "지도에 올리기"의 타입을 이렇게 못박아뒀고, 이 함수
    # 자신의 docstring도 "recommend의 후보 게시 전용"이라고 밝히고 있다. pin.created를 쓰면
    # recommend가 매번 type만 고쳐 새 Event를 만드는 우회가 필요해진다(recommend/flows.py에
    # 남아있던 것 — 이 수정으로 그 우회를 지웠다).
    event = core.pin_published_event(pin)
    return PinMutation(pin=pin_row, event=event)


def public_pin_payload(pin: Pin) -> dict:
    """전체 채널(SSE public) 이벤트에 싣는 핀 페이로드 — 보는 사람마다 다른 값(my_reaction)은 뺀다. 다른
    모듈(shortlist)이 공개 이벤트에 핀을 실을 때 같은 규칙을 재사용한다(#241)."""
    return core._public_pin_payload(pin)


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
    my_reaction = service.my_reactions_for_pins(db, [pin_row.id], viewer_id).get(pin_row.id)
    record = service.record_from_row(
        pin_row, lat=lat, lng=lng, reaction_counts=reaction_counts,
        created_by_display_name=display_name, my_reaction=my_reaction,
        place=places_api.get_places([pin_row.place_id], db=db).get(pin_row.place_id),
    )
    return core.to_pin_response(record, principal)


def count_public_pins_by_map(db: Session, map_ids: Sequence[str]) -> dict[str, int]:
    """maps(#313)가 Map.pin_count·InviteSummary.pin_count에 쓴다 — 삭제되지 않은 공개 핀 수.
    핀이 없는 지도는 0이다. 쿼리는 한 번이다. 비공개 핀(남의 AI 후보)은 세지 않는다(가드레일 1) —
    요청자 본인의 비공개 핀도 뺀다: 초대 요약은 비구성원도 보는 값이라 보는 사람마다 달라지면 안 된다."""
    counts = {map_id: 0 for map_id in map_ids}
    if not counts:
        return counts
    rows = db.execute(
        select(PinRow.map_id, func.count())
        .where(PinRow.map_id.in_(counts), PinRow.deleted_at.is_(None), PinRow.visibility == "public")
        .group_by(PinRow.map_id)
    ).all()
    counts.update({map_id: n for map_id, n in rows})
    return counts


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


def list_disliked_place_ids(db: Session, *, user_id: str, map_id: str, category: str) -> list[str]:
    """recommend의 가드레일 6(#119) — 이 사용자가 이 지도의 이 카테고리에서 🚫(against) 반응을
    남긴 핀들의 place_id(중복 없이, 정렬). recommend가 exclusions.reason='dismissed'로 쌓는다.

    소프트 삭제된 핀(`deleted_at` not null)도 **포함한다** — 다른 조회 함수와 달리 일부러다. 🚫는
    "이 장소는 싫다"는 이력이라 핀이 지워져도 사라지면 안 된다. 삭제된 핀의 장소는
    `list_place_ids_on_map`(살아 있는 핀만)에서 빠지므로, 여기서 잡지 않으면 거절한 장소가 다시
    추천된다."""
    rows = db.execute(
        select(PinRow.place_id)
        .select_from(ReactionRow)
        .join(PinRow, PinRow.id == ReactionRow.pin_id)
        .where(
            ReactionRow.user_id == user_id, ReactionRow.type == "against",
            PinRow.map_id == map_id, PinRow.category == category,
        )
        .distinct()
        .order_by(PinRow.place_id)
    ).scalars().all()
    return list(rows)


def list_reasoned_reactions(db: Session, *, map_id: str, category: str) -> list[dict]:
    """recommend의 근거 조립(①②, recommend/#108)이 쓴다 — 그 카테고리 핀에 남긴 반응 중
    사유가 있는 것만(반대는 사유 필수라 가드레일3로 항상 있고, 좋음/조율 필요도 사유가 있으면
    포함한다). llm.service.plan_evidence에 넘길 raw_reasons의 원자료다.

    소프트 삭제된 핀의 반응도 **포함한다**(#243) — 사유는 사람이 한 말이라 핀이 지워져도 사라지면 안 된다.
    구성원 누구나 핀을 지울 수 있어서(#25), 안 그러면 한 명이 b의 "조개 알러지" 핀을 지우는 것만으로 안전
    조건이 다음 run에서 빠진다(가드레일 8). 반대로 준비 판정(`count_reacted_users`)은 삭제 핀을 계속
    센다고 보지 않는다 — 사유(이력)와 "지금 몇 명이 반응했나"는 다른 질문이다. 같은 이유로
    `list_disliked_place_ids`도 삭제 핀을 포함한다."""
    rows = db.execute(
        select(
            ReactionRow.pin_id, ReactionRow.user_id, ReactionRow.type,
            ReactionRow.reason_text, ReactionRow.reason_chip_ids,
        )
        .select_from(ReactionRow)
        .join(PinRow, PinRow.id == ReactionRow.pin_id)
        .where(
            PinRow.map_id == map_id, PinRow.category == category,   # 삭제된 핀의 반응도 포함한다(#243)
            or_(ReactionRow.reason_text.is_not(None), func.jsonb_typeof(ReactionRow.reason_chip_ids) == "array"),   # 칩만 남긴 반대도(#236)
        )
    ).all()
    reasoned = []
    for pin_id, user_id, reaction_type, reason_text, reason_chip_ids in rows:
        if reason_text is None:
            if not reason_chip_ids:
                continue
            # 칩만 남긴 반대(#236) — 칩 id를 label로 바꿔 사유 문장으로 써서 ②가 구조화하게 한다(#60, #312).
            # 옛 값(이름 그대로 저장된 것)은 그대로 문장이 된다.
            reason_text = chips.reason_text_from_chips(reason_chip_ids)
        reasoned.append({
            "pin_id": str(pin_id), "user_id": user_id, "type": reaction_type,
            "reason_text": reason_text, "reason_chip_ids": reason_chip_ids,
        })
    return reasoned


def list_liked_pins(db: Session, *, map_id: str, category: str, requested_by: str) -> list[dict]:
    """recommend의 ♥ 선호 프로필(#112 1단계, #247)이 쓴다 — 이 카테고리의 삭제되지 않은 핀 중 ♥(like)를
    받은 것의 place_id와, 그 핀에 ♥를 누른 서로 다른 user_id 집합(`member_ids`)을 핀 하나당 한 항목으로
    돌려준다. 라벨은 pins가 알 필요 없다 — recommend가 place_id로 places의 라벨을 직접 읽는다.

    가드레일 1 — requested_by(이번 run의 요청자)에게 보이는 핀만 포함한다(공개 핀 + 본인의 비공개
    핀, `service.list_pins`의 가시성 판정과 같다). 안 그러면 다른 구성원의 비공개 AI 후보에 붙은
    ♥가 요청자의 선호 프로필에 섞여 남의 비공개 후보가 순위에 영향을 준다."""
    rows = db.execute(
        select(PinRow.id, PinRow.place_id, ReactionRow.user_id)
        .select_from(PinRow)
        .join(ReactionRow, ReactionRow.pin_id == PinRow.id)
        .where(
            PinRow.map_id == map_id, PinRow.category == category, PinRow.deleted_at.is_(None),
            or_(PinRow.visibility == "public", PinRow.created_by == requested_by),
            ReactionRow.type == "like",
        )
    ).all()
    grouped: dict[str, dict] = {}
    for pin_id, place_id, user_id in rows:
        entry = grouped.setdefault(str(pin_id), {"place_id": place_id, "member_ids": set()})
        entry["member_ids"].add(user_id)
    return list(grouped.values())


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


def delete_reactions_by_user(db: Session, *, user_id: str) -> int:
    """탈퇴(auth, #155)가 부른다 — 그 사용자가 남긴 모든 반응을 지우고 삭제 건수를 돌려준다.
    핀은 건드리지 않는다(작성 핀은 남는다). reaction.changed는 발행하지 않는다 — 탈퇴 시점의
    이벤트 정책은 auth 소관이고, 핀 목록을 다시 받으면 집계는 자연히 맞는다."""
    result = db.execute(delete(ReactionRow).where(ReactionRow.user_id == user_id))
    return result.rowcount


def delete_reactions_by_user_in_map(db: Session, *, user_id: str, map_id: str) -> int:
    """지도 나가기(maps, #369)가 부른다 — delete_reactions_by_user를 그 지도 하나로 좁힌 것.
    다른 지도에 남긴 반응은 그대로 둔다. 이벤트는 내지 않는다(maps가 member.left 하나로 알린다)."""
    pin_ids_on_map = select(PinRow.id).where(PinRow.map_id == map_id)
    result = db.execute(
        delete(ReactionRow).where(ReactionRow.user_id == user_id, ReactionRow.pin_id.in_(pin_ids_on_map))
    )
    return result.rowcount

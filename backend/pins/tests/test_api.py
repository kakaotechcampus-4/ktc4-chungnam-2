"""
pins/api.py — 다른 모듈(recommend/shortlist)이 부르는 접점의 테스트. 아직 그 모듈들이 없어
어떤 라우터도 이 파일을 실제로 호출하지 않지만, 방어 코드 2(세이브포인트)와 이벤트 조립을
포함한 실제 로직이라 테스트 없이 두면 위험하다 — mentor-review-plan.md의 §10 목록엔 없지만
docs/code-quality.md의 "테스트의 주장 내용" 기준에 맞춰 추가한다(for_Root.md에 기록).
"""

import uuid

from sqlalchemy import func, select

from common.events import EventLog
from pins import api
from pins.models import Pin as PinRow
from pins.schemas import Check


def test_create_ai_pin_inserts_public_ai_pin_and_returns_event(db_session):
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_ai_1",
        lat=35.1, lng=129.0, created_by="user_1",
    )
    assert mutation.pin.kind == "AI추천"
    assert mutation.pin.origin == "ai"
    assert mutation.pin.visibility == "public"

    assert mutation.event is not None
    # docs/events.md — 「지도에 올리기」 전용 이벤트는 pin.created가 아니라 pin.published다
    # (루트 수정, 2026-09-23 — recommend/#108 검증 중 발견된 기존 버그).
    assert mutation.event.type == "pin.published"
    assert mutation.event.map_id == "map_1"


_SAMPLE_CHECKS = [
    {"fact_key": "is_open", "label": "영업 중", "passed": True, "confidence": "known", "needs_check": False},
]


def test_create_ai_pin_stores_and_returns_checks(db_session):
    """#57/#124 — 게시 시점에 candidate.checks를 그대로 pins에 싣는다(가드레일 5)."""
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_checks_1",
        lat=35.1, lng=129.0, created_by="user_1", checks=_SAMPLE_CHECKS,
    )
    assert mutation.pin.checks == _SAMPLE_CHECKS
    assert mutation.event.payload["checks"] == _SAMPLE_CHECKS


def test_create_ai_pin_without_checks_stores_none(db_session):
    """기존 호출부(checks 파라미터를 안 넘기는 코드)가 그대로 동작해야 한다."""
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_checks_none",
        lat=35.1, lng=129.0, created_by="user_1",
    )
    assert mutation.pin.checks is None


def test_create_ai_pin_invalid_checks_raises_before_insert(db_session):
    """Check 스키마에 안 맞는 값(필드 누락)은 경계에서 바로 실패한다 — 잘못된 페이로드가
    그대로 저장되지 않는다."""
    from pydantic import ValidationError

    try:
        api.create_ai_pin(
            db_session, map_id="map_1", category="음식점", place_id="place_checks_invalid",
            lat=35.1, lng=129.0, created_by="user_1", checks=[{"fact_key": "is_open"}],
        )
        raise AssertionError("ValidationError가 발생했어야 한다")
    except ValidationError:
        pass

    rows = db_session.execute(
        select(PinRow).where(PinRow.place_id == "place_checks_invalid")
    ).scalars().all()
    assert rows == []


def test_create_ai_pin_duplicate_place_id_raises_pin_duplicate(db_session):
    from common.errors import AppError

    existing = PinRow(
        id=uuid.uuid4(), map_id="map_1", category="음식점", kind="일반", origin="direct",
        place_id="dup_ai_place",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(existing)
    db_session.commit()

    try:
        api.create_ai_pin(
            db_session, map_id="map_1", category="음식점", place_id="dup_ai_place",
            lat=35.1, lng=129.0, created_by="user_2",
        )
        raise AssertionError("PIN_DUPLICATE가 발생했어야 한다")
    except AppError as exc:
        assert exc.code == "PIN_DUPLICATE"
        assert exc.detail == {"pin_id": str(existing.id)}


def _insert_pin(db_session, *, map_id="map_1", kind="일반", origin="direct", created_by="user_1",
                 visibility="public"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind=kind, origin=origin,
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility=visibility, created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_mark_confirmed_sets_kind_to_confirmed(db_session):
    row = _insert_pin(db_session, kind="일반")
    mutation = api.mark_confirmed(db_session, pin_id=str(row.id), map_id="map_1")
    assert mutation.pin.kind == "확정"
    assert mutation.event is None


def test_mark_confirmed_cross_map_is_404(db_session):
    from common.errors import AppError

    row = _insert_pin(db_session, map_id="map_1")
    try:
        api.mark_confirmed(db_session, pin_id=str(row.id), map_id="other_map")
        raise AssertionError("NOT_FOUND이 발생했어야 한다")
    except AppError as exc:
        assert exc.code == "NOT_FOUND"


def test_unmark_confirmed_restores_kind_from_origin_ai(db_session):
    row = _insert_pin(db_session, kind="확정", origin="ai")
    mutation = api.unmark_confirmed(db_session, pin_id=str(row.id), map_id="map_1")
    assert mutation.pin.kind == "AI추천"


def test_unmark_confirmed_restores_kind_from_origin_direct(db_session):
    row = _insert_pin(db_session, kind="확정", origin="direct")
    mutation = api.unmark_confirmed(db_session, pin_id=str(row.id), map_id="map_1")
    assert mutation.pin.kind == "일반"


def test_get_pin_for_viewer_returns_own_private_pin(db_session):
    row = _insert_pin(db_session, visibility="private", created_by="user_1")
    result = api.get_pin_for_viewer(db_session, pin_id=str(row.id), viewer_id="user_1")
    assert result.id == row.id


def test_get_pin_for_viewer_other_users_private_pin_is_404(db_session):
    from common.errors import AppError

    row = _insert_pin(db_session, visibility="private", created_by="user_1")
    try:
        api.get_pin_for_viewer(db_session, pin_id=str(row.id), viewer_id="user_2")
        raise AssertionError("AI_PIN_PRIVATE가 발생했어야 한다")
    except AppError as exc:
        assert exc.code == "AI_PIN_PRIVATE"


def test_get_pin_response_for_viewer_fills_lat_lng_and_reaction_summary(db_session):
    """shortlist.flows가 ShortlistItem.pin 조립에 쓰는 함수 — service.list_pins과 같은 모양의
    Pin(lat/lng·reaction_summary·permissions 전부 채워짐)을 돌려주는지(for_Root.md 보고)."""
    from authz.core import Principal
    from pins.models import Reaction as ReactionRow

    row = _insert_pin(db_session, kind="확정")
    db_session.add(ReactionRow(pin_id=row.id, user_id="user_2", type="like"))
    db_session.commit()

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    pin = api.get_pin_response_for_viewer(db_session, pin_id=str(row.id), viewer_id="user_1", principal=principal)

    assert pin.id == str(row.id)
    assert pin.lat == 35.1
    assert pin.lng == 129.0
    assert pin.reaction_summary.like == 1
    assert pin.permissions.can_remove_from_shortlist is True  # kind=확정


def test_get_pin_response_for_viewer_returns_checks(db_session):
    from authz.core import Principal

    row = _insert_pin(db_session, kind="AI추천")
    row.checks = _SAMPLE_CHECKS
    db_session.commit()

    principal = Principal(user_id="user_1", map_id="map_1", role="member")
    pin = api.get_pin_response_for_viewer(db_session, pin_id=str(row.id), viewer_id="user_1", principal=principal)
    assert pin.checks == [Check(**c) for c in _SAMPLE_CHECKS]


def test_get_pin_response_for_viewer_other_users_private_pin_is_404(db_session):
    from authz.core import Principal
    from common.errors import AppError

    row = _insert_pin(db_session, visibility="private", created_by="user_1")
    principal = Principal(user_id="user_2", map_id="map_1", role="member")
    try:
        api.get_pin_response_for_viewer(db_session, pin_id=str(row.id), viewer_id="user_2", principal=principal)
        raise AssertionError("AI_PIN_PRIVATE가 발생했어야 한다")
    except AppError as exc:
        assert exc.code == "AI_PIN_PRIVATE"


def test_create_ai_pin_event_not_recorded_until_caller_calls_record_event(db_session):
    """api.py 자체는 record_event를 호출하지 않는다 — 이벤트를 반환만 하고, 커밋에
    무엇을 넣을지는 호출한 flow(recommend)가 결정한다(모듈 docstring 참고)."""
    api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_no_event",
        lat=35.1, lng=129.0, created_by="user_1",
    )
    rows = db_session.execute(select(EventLog).where(EventLog.map_id == "map_1")).scalars().all()
    assert rows == []


# ---------- list_disliked_place_ids (#119) ----------

def _react_on(db_session, pin, *, user_id, type):
    from pins.models import Reaction as ReactionRow

    db_session.add(ReactionRow(
        pin_id=pin.id, user_id=user_id, type=type, reason_text="사유" if type == "against" else None,
    ))
    db_session.commit()


def _pin_in(db_session, *, map_id="map_1", category="음식점"):
    row = _insert_pin(db_session, map_id=map_id)
    row.category = category
    db_session.commit()
    return row


def test_list_disliked_place_ids_returns_only_own_against_in_map_and_category(db_session):
    mine = _pin_in(db_session)
    _react_on(db_session, mine, user_id="user_1", type="against")
    liked = _pin_in(db_session)
    _react_on(db_session, liked, user_id="user_1", type="like")
    others = _pin_in(db_session)
    _react_on(db_session, others, user_id="user_2", type="against")
    other_category = _pin_in(db_session, category="카페")
    _react_on(db_session, other_category, user_id="user_1", type="against")
    other_map = _pin_in(db_session, map_id="map_2")
    _react_on(db_session, other_map, user_id="user_1", type="against")

    result = api.list_disliked_place_ids(db_session, user_id="user_1", map_id="map_1", category="음식점")

    assert result == [mine.place_id]


def test_list_disliked_place_ids_includes_soft_deleted_pins(db_session):
    """🚫는 이력이라 핀이 지워져도 남는다 — 다른 조회 함수와 달리 deleted_at을 거르지 않는다."""
    from datetime import datetime, timezone

    row = _pin_in(db_session)
    _react_on(db_session, row, user_id="user_1", type="against")
    row.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    assert api.list_disliked_place_ids(db_session, user_id="user_1", map_id="map_1", category="음식점") == [row.place_id]


def test_list_disliked_place_ids_is_empty_when_nothing_disliked(db_session):
    assert api.list_disliked_place_ids(db_session, user_id="user_1", map_id="map_1", category="음식점") == []

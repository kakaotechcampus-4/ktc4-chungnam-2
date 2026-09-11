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


def test_create_ai_pin_inserts_public_ai_pin_and_returns_event(db_session):
    mutation = api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_ai_1",
        lat=35.1, lng=129.0, created_by="user_1",
    )
    assert mutation.pin.kind == "AI추천"
    assert mutation.pin.origin == "ai"
    assert mutation.pin.visibility == "public"

    assert mutation.event is not None
    assert mutation.event.type == "pin.created"
    assert mutation.event.map_id == "map_1"


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


def test_create_ai_pin_event_not_recorded_until_caller_calls_record_event(db_session):
    """api.py 자체는 record_event를 호출하지 않는다 — 이벤트를 반환만 하고, 커밋에
    무엇을 넣을지는 호출한 flow(recommend)가 결정한다(모듈 docstring 참고)."""
    api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_no_event",
        lat=35.1, lng=129.0, created_by="user_1",
    )
    rows = db_session.execute(select(EventLog).where(EventLog.map_id == "map_1")).scalars().all()
    assert rows == []

"""shortlist_items·routes 테이블 CRUD 단위 테스트 — 실제 PostgreSQL 필요(conftest.py)."""

import uuid

import pytest
from sqlalchemy import func

from common.errors import AppError
from pins.models import Pin as PinRow
from shortlist import service
from shortlist.schemas import Route, RouteLeg


def _insert_pin(db_session, *, map_id="map_1"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_add_item_creates_row_and_returns_created_true(db_session):
    pin = _insert_pin(db_session)
    row, created = service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_1")
    assert created is True
    assert row.map_id == "map_1"
    assert row.pin_id == pin.id
    assert row.added_by == "user_1"


def test_add_item_twice_is_idempotent_and_returns_created_false(db_session):
    pin = _insert_pin(db_session)
    first, _ = service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_1")
    # 실제 요청 경계를 흉내낸다 — 프로덕션에서는 각 add_item 호출이 서로 다른 요청(각자
    # common.database.session_scope가 한 번 커밋)에서 온다. 커밋 없이 같은 세션에서 두 번
    # 부르면 두 번째 실패의 db.rollback()이 "마지막 커밋 지점"까지 되돌아가면서 아직
    # 커밋되지 않은 첫 번째 flush까지 함께 지워버린다(세이브포인트 범위 밖) — 이건 이 함수의
    # 버그가 아니라 테스트가 실제 요청 경계를 흉내내지 않은 탓이라 여기서 커밋으로 맞춘다.
    db_session.commit()
    second, created = service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_2")

    assert created is False
    assert second.id == first.id
    assert second.added_by == "user_1"  # 최초 등록자 그대로 — 재요청이 덮어쓰지 않는다


def test_add_item_twice_session_stays_usable_after_integrity_error(db_session):
    """add_item의 IntegrityError 복구가 begin_nested()+db.rollback() 조합으로 실제로 세션을
    되살리는지 — 복구 안 됐으면 아래 후속 쿼리가 PendingRollbackError로 죽는다
    (pins/service.py::create_pin과 동일한 위험, mentor-review-plan.md). 두 호출 사이에 커밋을
    둔다 — 이유는 위 test_add_item_twice_is_idempotent_and_returns_created_false 주석 참고."""
    pin = _insert_pin(db_session)
    service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_1")
    db_session.commit()
    service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_2")  # 두 번째 — IntegrityError 경로

    items = service.list_items(db_session, map_id="map_1")  # 복구 안 됐으면 여기서 죽는다
    assert len(items) == 1


def test_get_item_or_404_missing_raises(db_session):
    with pytest.raises(AppError) as exc:
        service.get_item_or_404(db_session, str(uuid.uuid4()))
    assert exc.value.code == "NOT_FOUND"


def test_get_item_or_404_bad_uuid_raises(db_session):
    with pytest.raises(AppError) as exc:
        service.get_item_or_404(db_session, "not-a-uuid")
    assert exc.value.code == "NOT_FOUND"


def test_delete_item_removes_row(db_session):
    pin = _insert_pin(db_session)
    row, _ = service.add_item(db_session, map_id="map_1", pin_id=str(pin.id), added_by="user_1")
    service.delete_item(db_session, str(row.id))

    with pytest.raises(AppError):
        service.get_item_or_404(db_session, str(row.id))


def test_list_items_orders_by_added_at(db_session):
    from datetime import datetime, timedelta, timezone

    from shortlist.models import ShortlistItem as ShortlistItemRow

    pin_a = _insert_pin(db_session)
    pin_b = _insert_pin(db_session)
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_a.id), added_by="user_1")
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_b.id), added_by="user_1")
    # server_default=func.now()는 트랜잭션 시작 시각을 돌려주므로(PostgreSQL), 이 테스트처럼 한
    # 트랜잭션 안에서 연달아 추가하면 added_at이 실제로 동일하다 — 그래서 명시적으로 값을
    # 벌려서 added_at 자체의 정렬을 검증한다(동률 시 2차 정렬 id는 test_list_items_tie_break_
    # by_id_when_added_at_matches가 따로 검증).
    now = datetime.now(timezone.utc)
    db_session.query(ShortlistItemRow).filter_by(pin_id=pin_a.id).update({"added_at": now})
    db_session.query(ShortlistItemRow).filter_by(pin_id=pin_b.id).update({"added_at": now + timedelta(seconds=1)})
    db_session.flush()

    items = service.list_items(db_session, map_id="map_1")
    assert [i.pin_id for i in items] == [pin_a.id, pin_b.id]


def test_list_items_tie_break_by_id_when_added_at_matches(db_session):
    """added_at이 동률이면(같은 트랜잭션에서 연달아 추가 — server_default=func.now()가
    트랜잭션 시작 시각을 돌려줘서 실제로 흔히 벌어진다) id를 2차 정렬 기준으로 써서, 같은
    데이터를 다시 조회해도 매번 같은 순서가 나오는지 확인한다(Antigravity 검수 지적 — 이전엔
    이 경우 DB 스캔 순서에 맡겨져 재계산할 때마다 동선이 달라질 수 있었다)."""
    pin_a = _insert_pin(db_session)
    pin_b = _insert_pin(db_session)
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_a.id), added_by="user_1")
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_b.id), added_by="user_1")

    first = [i.pin_id for i in service.list_items(db_session, map_id="map_1")]
    second = [i.pin_id for i in service.list_items(db_session, map_id="map_1")]
    assert first == second


def test_list_items_scoped_to_map(db_session):
    pin_a = _insert_pin(db_session, map_id="map_1")
    pin_b = _insert_pin(db_session, map_id="map_2")
    service.add_item(db_session, map_id="map_1", pin_id=str(pin_a.id), added_by="user_1")
    service.add_item(db_session, map_id="map_2", pin_id=str(pin_b.id), added_by="user_1")

    items = service.list_items(db_session, map_id="map_1")
    assert len(items) == 1
    assert items[0].pin_id == pin_a.id


def _route(region_label="구역 1", pin_ids=("pin_1", "pin_2")):
    return Route(
        region_label=region_label,
        ordered_pin_ids=list(pin_ids),
        total_distance_m=123.0,
        legs=[RouteLeg(from_pin_id=pin_ids[0], to_pin_id=pin_ids[1], distance_m=123.0, approx_minutes=2)],
    )


def test_replace_routes_inserts_rows(db_session):
    rows = service.replace_routes(db_session, map_id="map_1", routes=[_route()])

    assert len(rows) == 1
    assert rows[0].map_id == "map_1"
    assert rows[0].region_label == "구역 1"
    assert rows[0].ordered_pin_ids == ["pin_1", "pin_2"]
    assert rows[0].legs[0]["from_pin_id"] == "pin_1"


def test_replace_routes_deletes_previous_batch_before_inserting(db_session):
    service.replace_routes(db_session, map_id="map_1", routes=[_route(region_label="구역 1")])
    db_session.commit()

    service.replace_routes(db_session, map_id="map_1", routes=[_route(region_label="구역 A", pin_ids=("pin_3", "pin_4"))])

    rows = service.list_routes(db_session, map_id="map_1")
    assert len(rows) == 1  # 이전 배치("구역 1")는 지워지고 새 배치만 남는다
    assert rows[0].region_label == "구역 A"


def test_replace_routes_empty_list_clears_existing_rows(db_session):
    service.replace_routes(db_session, map_id="map_1", routes=[_route()])
    db_session.commit()

    service.replace_routes(db_session, map_id="map_1", routes=[])

    assert service.list_routes(db_session, map_id="map_1") == []


def test_list_routes_scoped_to_map(db_session):
    service.replace_routes(db_session, map_id="map_1", routes=[_route()])
    service.replace_routes(db_session, map_id="map_2", routes=[_route(region_label="구역 9")])

    assert len(service.list_routes(db_session, map_id="map_1")) == 1
    assert len(service.list_routes(db_session, map_id="map_2")) == 1

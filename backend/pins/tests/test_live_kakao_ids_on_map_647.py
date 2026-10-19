"""#647 — pins.api.list_live_kakao_ids_on_map: 추천 탭 광고의 「이미 지도에 있어요」가 실시간 핀을 카카오 장소 ID로 비교한다
(docs/ads.md 5절 4번). 실시간 핀(#382)에는 place_id가 없다."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from pins import api as pins_api
from pins.models import Pin as PinRow


def _live(db, kakao_place_id, *, map_id="map_1", deleted=False):
    db.add(PinRow(
        map_id=map_id, category="음식점", kind="일반", origin="direct", source="live", visibility="public",
        created_by="user_1", kakao_place_id=kakao_place_id, search_query="성수 칼국수",
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    ))
    db.flush()


def _db_pin(db, kakao_place_id, *, map_id="map_1"):
    db.add(PinRow(
        map_id=map_id, category="음식점", kind="일반", origin="direct", source="db", visibility="public",
        created_by="user_1", place_id=f"place_{uuid.uuid4().hex[:8]}", kakao_place_id=kakao_place_id,
        geom=func.ST_SetSRID(func.ST_MakePoint(127.0, 37.5), 4326),
    ))
    db.flush()


def _ids(db, map_id="map_1"):
    return pins_api.list_live_kakao_ids_on_map(db, map_id=map_id)


def test_returns_kakao_ids_of_live_pins_as_a_set(db_session):
    _live(db_session, "kakao:1001")
    _live(db_session, "kakao:2002")

    assert _ids(db_session) == {"kakao:1001", "kakao:2002"}


def test_deleted_live_pin_is_excluded(db_session):
    _live(db_session, "kakao:1001")
    _live(db_session, "kakao:3003", deleted=True)

    assert _ids(db_session) == {"kakao:1001"}


def test_db_pin_is_excluded_even_with_a_kakao_id(db_session):
    _live(db_session, "kakao:1001")
    _db_pin(db_session, "kakao:4004")   # db 핀은 place_id로 비교한다(list_place_ids_on_map)

    assert _ids(db_session) == {"kakao:1001"}


def test_other_map_is_excluded(db_session):
    _live(db_session, "kakao:1001", map_id="map_1")
    _live(db_session, "kakao:9009", map_id="map_2")

    assert _ids(db_session, "map_1") == {"kakao:1001"}
    assert _ids(db_session, "map_2") == {"kakao:9009"}


def test_map_without_live_pins_is_an_empty_set(db_session):
    _db_pin(db_session, "kakao:4004")

    assert _ids(db_session) == set()
    assert _ids(db_session, "map_none") == set()


def test_same_scope_as_list_live_kakao_place_ids(db_session):
    _live(db_session, "kakao:1001")
    _live(db_session, "kakao:3003", deleted=True)
    _db_pin(db_session, "kakao:4004")
    _live(db_session, "kakao:9009", map_id="map_2")

    assert _ids(db_session) == set(pins_api.list_live_kakao_place_ids(db_session, map_id="map_1"))


def test_read_only(db_session):
    _live(db_session, "kakao:1001")
    _ids(db_session)

    assert not db_session.dirty and not db_session.new

"""places.curated — --authoritative 적재가 켜고, 커버리지 적재·재계산은 끄지 않는다. 실제 PostgreSQL+PostGIS."""

import uuid

from sqlalchemy import select

from places import ingest, repository
from places.models import Place


def _row(source_id, name="가게", category="카페", status="open"):
    return ingest.PlaceRow("permit", source_id, name, category, "서울특별시 성동구 성수이로 1", None, 37.5445, 127.0561, status)


def _place(db, source_id):
    return db.execute(select(Place).where(Place.source == "permit", Place.source_id == source_id)).scalar_one()


def test_authoritative_load_sets_curated_for_new_and_existing_rows(db_session):
    repository.upsert_places(db_session, [_row("E1", "커버리지 이름", "음식점")], existing_mode="keep")
    assert _place(db_session, "E1").curated is False
    repository.upsert_places(db_session, [_row("E1", "정예 이름", "카페"), _row("E2")], existing_mode="overwrite")
    assert _place(db_session, "E1").curated is True     # 이미 있던 장소를 정예가 덮으면 켠다
    assert _place(db_session, "E2").curated is True     # 신규 정예 행도 true로 들어간다


def test_coverage_load_does_not_turn_curated_off_or_on(db_session):
    repository.upsert_places(db_session, [_row("F1")], existing_mode="overwrite")
    repository.upsert_places(db_session, [_row("F1", "커버리지 이름"), _row("F2")], existing_mode="keep")
    assert _place(db_session, "F1").curated is True and _place(db_session, "F1").name == "가게"
    assert _place(db_session, "F2").curated is False    # 신규 커버리지 행은 정예가 아니다


def test_refresh_mode_does_not_touch_curated_either_way(db_session):
    repository.upsert_places(db_session, [_row("G1")], existing_mode="overwrite")
    repository.upsert_places(db_session, [_row("G2")], existing_mode="refresh")
    repository.upsert_places(db_session, [_row("G1", "갱신")], existing_mode="refresh")
    assert _place(db_session, "G1").curated is True and _place(db_session, "G2").curated is False


def test_closing_a_curated_place_keeps_it_curated(db_session):
    repository.upsert_places(db_session, [_row("H1")], existing_mode="overwrite")
    repository.upsert_places(db_session, [_row("H1", status="closed")], existing_mode="keep")
    place = _place(db_session, "H1")
    assert place.status == "closed" and place.curated is True


def test_new_places_default_to_not_curated(db_session):
    p = Place(source="permit", source_id=uuid.uuid4().hex, name="직접", category="음식점", geom="SRID=4326;POINT(127.05 37.54)")
    db_session.add(p)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(Place, p.id).curated is False

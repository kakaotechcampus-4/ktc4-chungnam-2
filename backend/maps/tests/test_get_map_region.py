"""maps.api.get_map_region_label(#800)·get_map_region_center(#1059) — 지도의 여행 지역 이름과 중심 좌표. 읽기만 한다."""

from datetime import date, datetime, timezone

from sqlalchemy import func

from maps import api
from maps.models import Map


def _seed(db, *, label=None, deleted=False):
    row = Map(
        title="지도", start_date=date(2026, 10, 20), end_date=date(2026, 10, 22), created_by="user_1",
        region_label=label,
        region_center=func.ST_SetSRID(func.ST_MakePoint(127.73, 37.88), 4326) if label else None,
        deleted_at=datetime(2026, 10, 28, tzinfo=timezone.utc) if deleted else None,
    )
    db.add(row)
    db.flush()
    return row.id


def test_returns_region_label(db_session):
    assert api.get_map_region_label(db_session, _seed(db_session, label="춘천")) == "춘천"


def test_none_without_region_missing_or_deleted_map(db_session):
    assert api.get_map_region_label(db_session, _seed(db_session)) is None
    assert api.get_map_region_label(db_session, "no_such_map") is None
    assert api.get_map_region_label(db_session, _seed(db_session, label="춘천", deleted=True)) is None


def test_returns_region_center(db_session):
    lat, lng = api.get_map_region_center(db_session, _seed(db_session, label="춘천"))
    assert (round(lat, 6), round(lng, 6)) == (37.88, 127.73)


def test_center_none_without_region_missing_or_deleted_map(db_session):
    assert api.get_map_region_center(db_session, _seed(db_session)) is None
    assert api.get_map_region_center(db_session, "no_such_map") is None
    assert api.get_map_region_center(db_session, _seed(db_session, label="춘천", deleted=True)) is None

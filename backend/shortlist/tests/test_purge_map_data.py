"""api.purge_map_data(#431) — 대상 지도의 확정 항목·동선만 지운다. 핀(pins)은 건드리지 않는다."""

from pins.models import Pin
from shortlist import api
from shortlist.models import Route, ShortlistItem


def _seed(db, map_id):
    pin = Pin(
        map_id=map_id, category="음식점", kind="확정", origin="direct", source="live",
        kakao_place_id=f"kakao_{map_id}", search_query="맛집", visibility="public", created_by="u1",
    )
    db.add(pin)
    db.flush()
    db.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by="u1"))
    db.add(Route(map_id=map_id, region_label="홍대", ordered_pin_ids=[str(pin.id)], total_distance_m=0, legs=[]))
    db.add(Route(map_id=map_id, region_label="성수", ordered_pin_ids=[], total_distance_m=0, legs=[]))
    db.flush()


def test_purge_deletes_only_target_maps_items_and_routes(db_session):
    _seed(db_session, "gone")
    _seed(db_session, "keep")

    result = api.purge_map_data(db_session, map_ids=["gone"])

    assert result == {"shortlist_items": 1, "routes": 2}
    assert [i.map_id for i in db_session.query(ShortlistItem).all()] == ["keep"]
    assert {r.map_id for r in db_session.query(Route).all()} == {"keep"}
    assert db_session.query(Pin).count() == 2  # 핀은 pins가 지운다


def test_purge_with_no_map_ids_deletes_nothing(db_session):
    _seed(db_session, "keep")

    assert api.purge_map_data(db_session, map_ids=[]) == {"shortlist_items": 0, "routes": 0}
    assert db_session.query(ShortlistItem).count() == 1
    assert db_session.query(Route).count() == 2

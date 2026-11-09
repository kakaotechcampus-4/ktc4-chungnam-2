"""#1488 — get_pin_responses_for_viewer: 단건과 같은 응답을 배치로, 쿼리 수는 핀 수와 무관."""

import uuid

from sqlalchemy import event

from authz.core import Principal
from pins import api as pins_api
from pins.models import Reaction as ReactionRow
from pins.tests.test_pins_api import CAFE, KALGUKSU, _auth, _insert_pin


def _principal():
    return Principal(user_id="user_1", role="member", map_id="map_1")


def _post(app_client, body):
    return app_client.post("/maps/map_1/pins", json=body, cookies=_auth()).json()["id"]


def test_batch_matches_single_for_each_pin(app_client, db_session, fake_places):
    db_id, cafe_id = _post(app_client, KALGUKSU), _post(app_client, CAFE)
    live_id = _post(app_client, {"source": "live", "category": "음식점", "kakao_place_id": "kakao:9", "search_query": "곱창"})
    db_session.add_all([ReactionRow(pin_id=uuid.UUID(db_id), user_id="user_1", type="like"),
                        ReactionRow(pin_id=uuid.UUID(db_id), user_id="user_2", type="against", reason_text="멀어요")])
    db_session.commit()
    ids = [db_id, cafe_id, live_id]
    batch = pins_api.get_pin_responses_for_viewer(db_session, pin_ids=ids, viewer_id="user_1", principal=_principal())
    for pin_id in ids:
        single = pins_api.get_pin_response_for_viewer(db_session, pin_id=pin_id, viewer_id="user_1", principal=_principal())
        assert batch[pin_id].model_dump() == single.model_dump()
    assert batch[db_id].my_reaction


def test_missing_deleted_invalid_and_duplicate_ids(db_session):
    alive, gone = _insert_pin(db_session), _insert_pin(db_session, deleted=True)
    out = pins_api.get_pin_responses_for_viewer(
        db_session, pin_ids=[str(alive.id), str(alive.id), str(gone.id), str(uuid.uuid4()), "not-a-uuid"],
        viewer_id="user_1", principal=_principal())
    assert list(out) == [str(alive.id)]
    assert pins_api.get_pin_responses_for_viewer(db_session, pin_ids=[], viewer_id="user_1", principal=_principal()) == {}


def test_query_count_does_not_grow_with_pins(db_session):
    engine = db_session.get_bind().engine
    statements: list[str] = []

    def on_execute(conn, cursor, statement, *args):
        statements.append(statement)

    def count(ids):
        statements.clear()
        event.listen(engine, "before_cursor_execute", on_execute)
        try:
            pins_api.get_pin_responses_for_viewer(db_session, pin_ids=ids, viewer_id="user_1", principal=_principal())
        finally:
            event.remove(engine, "before_cursor_execute", on_execute)
        return len(statements)

    pins = [str(_insert_pin(db_session, created_by=f"user_{i}").id) for i in range(6)]
    assert count(pins[:1]) == count(pins)

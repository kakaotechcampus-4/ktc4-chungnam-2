from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from auth.testing import session_cookie
from maintenance import run
from pins import api as pins_api

pytest_plugins = ("pins.tests.conftest",)

DELETED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_pins_dry_run_boundary_and_idempotence(app_client, db_session, monkeypatch, capsys):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return DELETED_AT.astimezone(tz)

    monkeypatch.setattr("pins.service.datetime", FrozenDatetime)
    pin = pins_api.create_ai_pin(
        db_session, map_id="map_1", category="음식점", place_id="place_1",
        lat=37.5, lng=127.0, created_by="user_1",
    ).pin
    db_session.commit()
    cookies = session_cookie("user_1")
    assert app_client.put(f"/pins/{pin.id}/reaction", json={"type": "like"}, cookies=cookies).status_code == 200
    assert app_client.delete(f"/pins/{pin.id}", cookies=cookies).status_code == 204

    factory = sessionmaker(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    at_boundary = DELETED_AT + timedelta(days=30)

    def execute(now, *args):
        code = run.main(["--only", "pins", *args], session_factory=factory, now=now)
        return code, capsys.readouterr().out

    assert "pins: 0행" in execute(at_boundary - timedelta(microseconds=1))[1]
    assert "pins: 2행" in execute(at_boundary, "--dry-run")[1]
    code, report = execute(at_boundary)
    assert code == 0 and "pins: 2행" in report
    assert "pins: 0행" in execute(at_boundary)[1]

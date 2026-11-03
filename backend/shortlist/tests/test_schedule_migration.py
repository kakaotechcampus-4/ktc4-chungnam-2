"""확장 마이그레이션이 기존 행을 보존하고 되돌린 뒤 다시 적용된다."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


def test_schedule_migration_preserves_existing_rows(db_session, monkeypatch):
    connection = db_session.connection()
    connection.execute(text("CREATE TEMPORARY TABLE shortlist_items (id integer PRIMARY KEY, visit_order integer) ON COMMIT DROP"))
    connection.execute(text("INSERT INTO shortlist_items VALUES (1, 7)"))
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0059_shortlist_scheduled_date.py"
    spec = importlib.util.spec_from_file_location("schedule_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    migration.upgrade()
    assert connection.execute(text("SELECT id, visit_order, scheduled_date FROM shortlist_items")).one() == (1, 7, None)
    migration.downgrade()
    assert connection.execute(text("SELECT id, visit_order FROM shortlist_items")).one() == (1, 7)
    migration.upgrade()
    assert connection.execute(text("SELECT id, visit_order, scheduled_date FROM shortlist_items")).one() == (1, 7, None)

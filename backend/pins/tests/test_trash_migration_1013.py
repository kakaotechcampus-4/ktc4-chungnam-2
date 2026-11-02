"""#1013 — 실제 PostGIS DB에서 삭제 기록 expand, 기존 행 보존, down/up을 확인한다."""

from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from pins.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME

REVISION = "0056_pin_trash"
PREVIOUS = "0055_place_external_ids"


def _config():
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    return cfg


@pytest.fixture
def migration_engine(monkeypatch):
    url = make_url(BASE_DATABASE_URL)
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert TEST_DB_NAME.startswith("pingo_test")
    name = f"{TEST_DB_NAME[:40]}_trash_{uuid4().hex[:8]}"
    admin = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    target = url.set(database=name)
    engine = sa.create_engine(target)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def test_migration_chain_is_single_and_revision_fits():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert all(len(rev.revision) <= 32 for rev in script.walk_revisions())


def test_trash_upgrade_preserves_old_rows_and_downgrade_is_reversible(migration_engine):
    cfg = _config()
    engine = migration_engine
    command.upgrade(cfg, PREVIOUS)
    with engine.begin() as conn:
        conn.execute(sa.text("""
            INSERT INTO pins (id, map_id, category, kind, origin, visibility, created_by, deleted_at, place_id, geom)
            VALUES ('00000000-0000-0000-0000-000000000001', 'trash_migration', '음식점', '일반',
                    'direct', 'public', 'user_1', NULL, 'migration_place_1', ST_GeogFromText('POINT(127 37.5)')),
                   ('00000000-0000-0000-0000-000000000002', 'trash_migration', '음식점', '일반',
                    'direct', 'public', 'user_1', '2026-10-01T00:00:00Z', 'migration_place_2', ST_GeogFromText('POINT(127 37.5)'))
        """))
        before = conn.execute(sa.text("SELECT id, deleted_at FROM pins ORDER BY id")).all()
    command.upgrade(cfg, "head")
    columns = {col["name"]: col for col in sa.inspect(engine).get_columns("pins")}
    assert columns["deleted_by"]["nullable"] and columns["deleted_was_confirmed"]["nullable"]
    assert isinstance(columns["deleted_by"]["type"], sa.String)
    assert isinstance(columns["deleted_was_confirmed"]["type"], sa.Boolean)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT id, deleted_at FROM pins ORDER BY id")).all() == before
        assert conn.execute(sa.text("SELECT deleted_by, deleted_was_confirmed FROM pins")).all() == [(None, None)] * 2
        index = conn.scalar(sa.text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_pins_deleted_at'"))
        assert "WHERE (deleted_at IS NOT NULL)" in index
    command.downgrade(cfg, PREVIOUS)
    columns = {col["name"] for col in sa.inspect(engine).get_columns("pins")}
    assert "deleted_by" not in columns and "deleted_was_confirmed" not in columns
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT id, deleted_at FROM pins ORDER BY id")).all() == before
        assert conn.scalar(sa.text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_pins_deleted_at'")) == 0
    command.upgrade(cfg, "head")
    assert "deleted_by" in {col["name"] for col in sa.inspect(engine).get_columns("pins")}

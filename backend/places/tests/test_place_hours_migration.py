"""마이그레이션 0038_place_hours up/down — 0037까지 올린 DB에 place_hours가 생기고 내려가면 사라진다. models.py와 어긋나지 않았는지도 본다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_hrs_mig` DB를 따로 만들고 끝나면 지운다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from places.models import PlaceHours
from places.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, _replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0038_place_hours"
PREVIOUS = "0037_agent_course_runs"
MIG_DB = f"{TEST_DB_NAME}_hrs_mig"[:63]


@pytest.fixture()
def mig_url(monkeypatch):
    admin = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIG_DB}"'))
    url = _replace_dbname(BASE_DATABASE_URL, MIG_DB)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)   # alembic/env.py가 읽는다
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    cfg = Config()   # alembic.ini를 넘기지 않는다 — env.py가 fileConfig로 로깅을 다시 설정해 caplog 테스트를 깨뜨린다
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _columns(url):
    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        return {c["name"]: c for c in insp.get_columns("place_hours")} if insp.has_table("place_hours") else None
    finally:
        engine.dispose()


def test_chain_has_a_single_head_and_this_revision_follows_agent_course_runs():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_creates_the_table_matching_the_model_and_downgrade_drops_it(mig_url):
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    assert _columns(mig_url) is None
    command.upgrade(cfg, REVISION)
    cols = _columns(mig_url)
    assert set(cols) == set(PlaceHours.__table__.c.keys())
    assert {n: c["nullable"] for n, c in cols.items()} == {"place_id": False, "hours": True, "closed_days": True, "closed_note": True, "hours_note": True, "updated_at": False}
    engine = sa.create_engine(mig_url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO places (id, source, source_id, name, category, geom, status) VALUES "
                             "('00000000-0000-0000-0000-000000000001', 'permit', 'A', 'A', '음식점', ST_GeogFromText('POINT(127 37.5)'), 'open')"))
        conn.execute(sa.text("INSERT INTO place_hours (place_id, closed_days) VALUES ('00000000-0000-0000-0000-000000000001', ARRAY['월'])"))
        conn.execute(sa.text("DELETE FROM places"))   # on delete cascade
        assert conn.scalar(sa.text("SELECT count(*) FROM place_hours")) == 0
    engine.dispose()
    command.downgrade(cfg, PREVIOUS)
    assert _columns(mig_url) is None
    command.upgrade(cfg, REVISION)
    assert _columns(mig_url) is not None

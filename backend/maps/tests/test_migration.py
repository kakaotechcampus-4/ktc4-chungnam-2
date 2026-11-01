"""마이그레이션 0053_maps_withdrawal_marker(#1000) up/down — 빈 DB에 올리고 내렸다 다시 올린다. models.py와 어긋나지 않았는지도 본다.

`<PINGO_TEST_DB>_maps_mig` DB를 따로 만들고 끝나면 지운다(llm/tests/test_migration.py와 같은 방식).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from agent.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname
from maps.models import Map

BACKEND = Path(__file__).resolve().parents[2]
REVISION, PREVIOUS = "0053_maps_withdrawal_marker", "0052_llm_calls_batch_discard"
MIG_DB = f"{TEST_DB_NAME}_maps_mig"[:63]


@pytest.fixture()
def mig_url(monkeypatch):
    admin = sa.create_engine(replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIG_DB}"'))
    url = replace_dbname(BASE_DATABASE_URL, MIG_DB)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    cfg = Config()   # alembic.ini를 넘기지 않는다 — 로깅 설정을 다시 하면 caplog 테스트가 깨진다(agent/tests/test_migration.py)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_upgrade_matches_model_and_downgrades(mig_url):
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    engine = sa.create_engine(mig_url)
    try:
        assert "deleted_by_withdrawal_of" not in {c["name"] for c in sa.inspect(engine).get_columns("maps")}
        with engine.begin() as conn:   # 기존 행은 새 열이 NULL이어야 한다
            conn.execute(sa.text(
                "INSERT INTO maps (id, title, start_date, end_date, created_by) VALUES ('m1', 't', '2026-11-01', '2026-11-02', 'u1')"
            ))

        command.upgrade(cfg, REVISION)
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("maps")} == set(Map.__table__.columns.keys())
        assert {i.name for i in Map.__table__.indexes} <= {i["name"] for i in inspector.get_indexes("maps")}
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT deleted_by_withdrawal_of FROM maps WHERE id = 'm1'")).scalar_one() is None

        command.downgrade(cfg, PREVIOUS)
        assert "deleted_by_withdrawal_of" not in {c["name"] for c in sa.inspect(engine).get_columns("maps")}
        command.upgrade(cfg, REVISION)
        assert "deleted_by_withdrawal_of" in {c["name"] for c in sa.inspect(engine).get_columns("maps")}
    finally:
        engine.dispose()

"""마이그레이션 0037_agent_course_runs up/down — 빈 DB에 올리고 내렸다 다시 올린다. models.py와 어긋나지 않았는지도 본다.

`<PINGO_TEST_DB>_course_mig` DB를 따로 만들고 끝나면 지운다(agent/tests/test_migration.py와 같은 방식).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from agent.course.models import AgentCourseRun
from agent.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[3]
REVISION, PREVIOUS = "0037_agent_course_runs", "0036_ads"
MIG_DB = f"{TEST_DB_NAME}_course_mig"[:63]


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


def test_chain_has_one_head_and_contains_course_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert REVISION in {r.revision for r in script.walk_revisions()}


def test_upgrade_matches_model_enforces_single_active_run_and_downgrades(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("agent_course_runs")} == set(AgentCourseRun.__table__.columns.keys())
        indexes = {i["name"]: i for i in inspector.get_indexes("agent_course_runs")}
        assert {"ix_agent_course_runs_map_user", "ix_agent_course_runs_user_created", "uq_agent_course_runs_active"} <= set(indexes)
        assert indexes["uq_agent_course_runs_active"]["unique"]

        insert = sa.text(
            "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_pin_ids)"
            " VALUES (gen_random_uuid(), 'm1', 'u1', :status, '{}', now(), '[]')"
        )
        with engine.begin() as conn:
            conn.execute(insert, {"status": "done"})
            conn.execute(insert, {"status": "failed"})
            conn.execute(insert, {"status": "running"})
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:   # 진행 중은 (지도, 요청자)당 하나
            conn.execute(insert, {"status": "queued"})

        command.downgrade(cfg, PREVIOUS)
        assert "agent_course_runs" not in set(sa.inspect(engine).get_table_names())
        command.upgrade(cfg, REVISION)
        assert "agent_course_runs" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

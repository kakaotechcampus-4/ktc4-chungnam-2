"""마이그레이션 0037_agent_course_runs와 0050(하루 상한 인덱스 삭제, #976) up/down — 빈 DB에 올리고 내렸다 다시 올린다.
models.py와 어긋나지 않았는지도 본다.

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
DROP_INDEX_REVISION, DROP_INDEX_PREVIOUS = "0050_drop_course_user_index", "0049_reviews"
DROPPED_INDEX = "ix_agent_course_runs_user_created"   # 하루 상한을 세던 자리(0037). 상한이 크레딧으로 바뀌어(#950) 0050에서 지운다
MODEL_INDEXES = {i.name for i in AgentCourseRun.__table__.indexes}
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


def test_chain_has_one_head_and_contains_course_revisions():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert {REVISION, DROP_INDEX_REVISION} <= {r.revision for r in script.walk_revisions()}


def test_upgrade_matches_model_enforces_single_active_run_and_downgrades(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("agent_course_runs")} == set(AgentCourseRun.__table__.columns.keys())
        indexes = {i["name"]: i for i in inspector.get_indexes("agent_course_runs")}
        assert set(indexes) == MODEL_INDEXES | {DROPPED_INDEX}   # 0037 시점에는 0050에서 지울 인덱스가 아직 있다
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


def _index_columns(engine) -> dict[str, list[str]]:
    return {i["name"]: i["column_names"] for i in sa.inspect(engine).get_indexes("agent_course_runs")}


def test_0050_drops_user_created_index_matches_model_and_downgrade_restores_it(mig_url):
    cfg = _config()
    command.upgrade(cfg, DROP_INDEX_PREVIOUS)
    engine = sa.create_engine(mig_url)
    try:
        before = _index_columns(engine)
        assert before[DROPPED_INDEX] == ["requested_by", "created_at"]

        command.upgrade(cfg, DROP_INDEX_REVISION)
        after = _index_columns(engine)
        assert set(after) == MODEL_INDEXES   # 모델과 DB가 같다
        assert DROPPED_INDEX not in after

        command.downgrade(cfg, DROP_INDEX_PREVIOUS)
        assert _index_columns(engine) == before   # 0037과 같은 모양으로 돌아온다
        command.upgrade(cfg, DROP_INDEX_REVISION)
        assert set(_index_columns(engine)) == MODEL_INDEXES
    finally:
        engine.dispose()

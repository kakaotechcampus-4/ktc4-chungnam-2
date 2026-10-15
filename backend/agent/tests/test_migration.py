"""마이그레이션 0029_agent_tables, 0030_agent_cursor_drop_gap_seq up/down — 빈 DB에 head까지 올리고, 0025로 내렸다가
다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_agent_mig` DB를 따로 만들고 끝나면 지운다.
models.py와 마이그레이션이 어긋나지 않았는지도 여기서 본다(컬럼 이름, 부분 유니크 인덱스).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)
from agent.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0030_agent_cursor_drop_gap_seq"   # agent 마지막 마이그레이션(뒤에 다른 모듈 것이 붙어도 된다)
TABLES_REVISION = "0029_agent_tables"
PREVIOUS = "0025_invite_revoke"
MODELS = (AgentSettings, AgentCursor, AgentRun, AgentSuggestion, AgentSuggestionView, AgentReasonSummary, AgentRunAdvice)
TABLES = {m.__tablename__ for m in MODELS}
MIG_DB = f"{TEST_DB_NAME}_agent_mig"[:63]


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
    monkeypatch.setenv("DATABASE_URL", url)  # alembic/env.py가 읽는다

    yield url

    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    # alembic.ini를 넘기지 않는다 — 넘기면 env.py가 fileConfig로 로깅 설정을 다시 하면서 이미 있던 로거를 꺼서,
    # 같은 pytest 실행의 caplog 테스트(llm/tests/test_failure_logging.py 등)가 로그를 못 받는다
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _tables(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def test_chain_has_one_head_and_contains_agent_revisions():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert {REVISION, TABLES_REVISION} <= {r.revision for r in script.walk_revisions()}


def test_upgrade_creates_tables_matching_models_and_downgrade_removes_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= _tables(engine)
        for model in MODELS:
            columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
            assert columns == set(model.__table__.columns.keys()), model.__tablename__

        indexes = {i["name"]: i for i in inspector.get_indexes("agent_suggestions")}
        active = indexes["uq_agent_suggestions_active"]
        assert active["unique"] and active["column_names"] == ["map_id"]
        # PostgreSQL이 "((status)::text = 'active'::text)"로 바꿔 돌려준다
        predicate = active["dialect_options"]["postgresql_where"].replace("::text", "").replace("(", "").replace(")", "")
        assert predicate == "status = 'active'"
        assert "ix_agent_suggestions_map_fp" in indexes
        assert "ix_agent_runs_map_started" in {i["name"] for i in inspector.get_indexes("agent_runs")}

        # 부분 유니크 인덱스가 실제로 지도당 active 하나만 받는다
        insert = sa.text(
            "INSERT INTO agent_suggestions (id, map_id, diagnosis, fingerprint, evidence_hash, title, claims, advice,"
            " actions, status, expires_at) VALUES (gen_random_uuid(), 'm1', 'stall', 'fp', 'eh', 't', '[]', '[]',"
            " '[]', :status, now())"
        )
        with engine.begin() as conn:
            conn.execute(insert, {"status": "dismissed"})
            conn.execute(insert, {"status": "active"})
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"status": "active"})

        # 0030만 내리면 gap_seq가 빈 칸으로 돌아온다(#525 전 모양)
        command.downgrade(cfg, TABLES_REVISION)
        assert "gap_seq" in {c["name"] for c in sa.inspect(engine).get_columns("agent_cursors")}

        command.downgrade(cfg, PREVIOUS)
        assert not (TABLES & _tables(engine))

        command.upgrade(cfg, REVISION)  # 다시 올려도 깨지지 않는다
        assert TABLES <= _tables(engine)
    finally:
        engine.dispose()

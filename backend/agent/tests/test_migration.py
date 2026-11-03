"""마이그레이션 0029_agent_tables, 0030_agent_cursor_drop_gap_seq, 0047, 0056(현황 문단과 facts, #1168) up/down — 빈 DB에 head까지 올리고, 0025로 내렸다가
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
    AgentMapStatus,
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
LEASE_REVISION = "0047_agent_cursor_lease_token"
STATUS_REVISION = "0056_agent_map_status_facts"   # agent_map_status 테이블, agent_suggestions.facts(#1168)
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
    assert len(script.get_heads()) == 1                          # 체인은 하나다
    assert REVISION in {r.revision for r in script.walk_revisions()}   # 뒤에 다른 모듈 마이그레이션이 붙어도 된다


def test_upgrade_creates_tables_matching_models_and_downgrade_removes_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= _tables(engine)
        for model in MODELS:
            columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
            later = {AgentCursor: {"lease_token"}, AgentSuggestion: {"facts"}, AgentRunAdvice: {"state_key"}}.get(model, set())
            assert columns == set(model.__table__.columns.keys()) - later, model.__tablename__   # 0047, 0056, 0057이 더한다(아래)

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

        # 0056이 현황 문단 테이블과 facts를 더하고(#1168), 모델과 칸이 같다. 기존 제안의 facts는 빈 목록이다
        command.upgrade(cfg, STATUS_REVISION)
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("agent_map_status")} == set(AgentMapStatus.__table__.columns.keys())
        assert "facts" in {c["name"] for c in inspector.get_columns("agent_suggestions")}
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT facts FROM agent_suggestions")).scalars().all() == [[], []]
        command.downgrade(cfg, LEASE_REVISION)
        assert "agent_map_status" not in _tables(engine)
        assert "facts" not in {c["name"] for c in sa.inspect(engine).get_columns("agent_suggestions")}

        # 0047이 lease_token을 더하고, 내리면 지운다(#812)
        command.upgrade(cfg, LEASE_REVISION)
        assert "lease_token" in {c["name"] for c in sa.inspect(engine).get_columns("agent_cursors")}
        command.downgrade(cfg, REVISION)
        assert "lease_token" not in {c["name"] for c in sa.inspect(engine).get_columns("agent_cursors")}

        # 0030만 내리면 gap_seq가 빈 칸으로 돌아온다(#525 전 모양)
        command.downgrade(cfg, TABLES_REVISION)
        assert "gap_seq" in {c["name"] for c in sa.inspect(engine).get_columns("agent_cursors")}

        command.downgrade(cfg, PREVIOUS)
        assert not (TABLES & _tables(engine))

        command.upgrade(cfg, REVISION)  # 다시 올려도 깨지지 않는다
        assert TABLES <= _tables(engine)
    finally:
        engine.dispose()


def test_advice_state_key_migration_is_expand_only(mig_url):
    """0057은 칸 하나만 더한다(#1103) — 기본키는 run_id 그대로라 이전 서버의 ON CONFLICT (run_id) DO NOTHING도 돈다."""
    cfg = _config()
    command.upgrade(cfg, "0056_agent_map_status_facts")
    engine = sa.create_engine(mig_url)
    insert = sa.text(
        "INSERT INTO agent_run_advice (run_id, map_id, claims, advice, actions, created_at) "
        "VALUES ('00000000-0000-0000-0000-000000001103', 'm1103', '[]', '[]', '[]', '2026-11-01') "
        "ON CONFLICT (run_id) DO NOTHING"
    )
    try:
        with engine.begin() as conn:
            conn.execute(insert)
        command.upgrade(cfg, "head")
        inspector = sa.inspect(engine)
        assert inspector.get_pk_constraint("agent_run_advice")["constrained_columns"] == ["run_id"]
        assert {c["name"] for c in inspector.get_columns("agent_run_advice")} == set(AgentRunAdvice.__table__.columns.keys())
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT state_key FROM agent_run_advice")).scalar_one() == ""
            conn.execute(insert)   # 이전 서버의 쓰기가 새 스키마에서 그대로 돈다
        command.downgrade(cfg, "0056_agent_map_status_facts")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM agent_run_advice")).scalar_one() == 1
        assert "state_key" not in {c["name"] for c in sa.inspect(engine).get_columns("agent_run_advice")}
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()

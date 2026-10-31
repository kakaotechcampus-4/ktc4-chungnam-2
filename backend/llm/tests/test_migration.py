"""마이그레이션 0043_llm_calls up/down — 빈 DB에 올리고 내렸다 다시 올린다. models.py와 어긋나지 않았는지도 본다(#870).

`<PINGO_TEST_DB>_llm_mig` DB를 따로 만들고 끝나면 지운다(agent/course/tests/test_migration.py와 같은 방식).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from agent.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname
from llm.models import LlmCall

BACKEND = Path(__file__).resolve().parents[2]
REVISION, PREVIOUS = "0043_llm_calls", "0042_places_trgm_search"
MIG_DB = f"{TEST_DB_NAME}_llm_mig"[:63]


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
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("llm_calls")} == set(LlmCall.__table__.columns.keys())
        assert {i.name for i in LlmCall.__table__.indexes} == {i["name"] for i in inspector.get_indexes("llm_calls")}

        with engine.begin() as conn:   # 토큰·비용은 기본값 0
            conn.execute(sa.text(
                "INSERT INTO llm_calls (id, feature, call, trace_id, model, outcome, ok, elapsed_ms)"
                " VALUES (gen_random_uuid(), 'course', 'course_goals', gen_random_uuid(), 'gpt-6-luna', 'ok', true, 1)"
            ))
            assert conn.execute(sa.text("SELECT input_tokens + cached_input_tokens + output_tokens, cost_krw FROM llm_calls")).one() == (0, 0)

        command.downgrade(cfg, PREVIOUS)
        assert "llm_calls" not in set(sa.inspect(engine).get_table_names())
        command.upgrade(cfg, REVISION)
        assert "llm_calls" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

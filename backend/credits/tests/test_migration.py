"""마이그레이션 0048_credits up/down — 빈 DB에 0048까지 올리고, 0047로 내렸다가 다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_credits_mig` DB를 따로 만들고 끝나면 지운다.
models.py와 마이그레이션이 어긋나지 않았는지(칸 이름, CHECK, UNIQUE, 인덱스, FK 없음)도 여기서 본다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from credits.models import CreditAccount, CreditLedger
from credits.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0048_credits"
PREVIOUS = "0047_agent_cursor_lease_token"
MODELS = (CreditAccount, CreditLedger)
TABLES = {m.__tablename__ for m in MODELS}
MIG_DB = f"{TEST_DB_NAME}_credits_mig"[:63]


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
    # alembic.ini를 넘기지 않는다 — env.py의 fileConfig가 다른 테스트의 로거를 끈다(ads/tests/test_migration.py와 같은 이유)
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_chain_has_one_head_and_contains_the_credits_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_creates_tables_matching_models_and_downgrade_removes_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        for model in MODELS:
            columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
            assert columns == set(model.__table__.columns.keys()), model.__tablename__
            assert inspector.get_foreign_keys(model.__tablename__) == []   # 사용자 id에 FK를 걸지 않는다(#760)

        [index] = [i for i in inspector.get_indexes("credit_ledger") if i["name"] == "ix_credit_ledger_user_reason_created"]
        assert index["column_names"] == ["user_id", "reason", "created_at"]
        assert [u["column_names"] for u in inspector.get_unique_constraints("credit_ledger")] == [["ref_id"]]

        ledger = sa.text("INSERT INTO credit_ledger (id, user_id, delta, reason, ref_id) "
                         "VALUES (gen_random_uuid(), 'u1', 30, 'initial', :ref)")
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO credit_accounts (user_id, balance) VALUES ('u1', 0)"))
            conn.execute(ledger, {"ref": "initial:u1"})
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(ledger, {"ref": "initial:u1"})                       # ref_id UNIQUE
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text("UPDATE credit_accounts SET balance = -1"))  # balance >= 0

        command.downgrade(cfg, PREVIOUS)
        assert not (TABLES & set(sa.inspect(engine).get_table_names()))

        command.upgrade(cfg, REVISION)
        assert TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

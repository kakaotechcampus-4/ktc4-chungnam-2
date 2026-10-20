"""마이그레이션 0036_ads up/down — 빈 DB에 0036까지 올리고, 0035로 내렸다가 다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_ads_mig` DB를 따로 만들고 끝나면 지운다.
models.py와 마이그레이션이 어긋나지 않았는지(칸 이름, 부분 유니크, CHECK, FK 없음)도 여기서 본다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from ads.models import Ad, AdDailyStat
from ads.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0036_ads"
PREVIOUS = "0035_users_guest"
MODELS = (Ad, AdDailyStat)
TABLES = {m.__tablename__ for m in MODELS}
MIG_DB = f"{TEST_DB_NAME}_ads_mig"[:63]


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
    # alembic.ini를 넘기지 않는다 — env.py의 fileConfig가 다른 테스트의 로거를 끈다(agent/tests/test_migration.py와 같은 이유)
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_chain_has_one_head_and_contains_the_ads_revision():
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

        [active] = [i for i in inspector.get_indexes("ads") if i["name"] == "uq_ads_place_active"]
        assert active["unique"] and active["column_names"] == ["place_id"]
        assert active["dialect_options"]["postgresql_where"] == "active"
        assert inspector.get_foreign_keys("ads") == []                     # places에 FK를 걸지 않는다
        [fk] = inspector.get_foreign_keys("ad_daily_stats")
        assert (fk["referred_table"], fk["constrained_columns"]) == ("ads", ["ad_id"])
        assert inspector.get_pk_constraint("ad_daily_stats")["constrained_columns"] == ["ad_id", "stat_date"]

        insert = sa.text("INSERT INTO ads (id, place_id, starts_at, ends_at, active) VALUES "
                         "(gen_random_uuid(), :p, now(), now() + :d * interval '1 day', :a)")
        with engine.begin() as conn:
            conn.execute(insert, {"p": "p1", "d": 1, "a": True})
            conn.execute(insert, {"p": "p1", "d": 1, "a": False})          # inactive는 여러 개여도 된다
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"p": "p1", "d": 1, "a": True})           # 같은 장소 active는 하나
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"p": "p2", "d": 0, "a": True})           # starts_at < ends_at

        command.downgrade(cfg, PREVIOUS)
        assert not (TABLES & set(sa.inspect(engine).get_table_names()))

        command.upgrade(cfg, REVISION)
        assert TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

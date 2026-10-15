"""마이그레이션 0031_notifications up/down — 빈 DB에 head까지 올리고, 0030으로 내렸다가 다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_notif_mig` DB를 따로 만들고 끝나면 지운다.
models.py와 마이그레이션이 어긋나지 않았는지도 여기서 본다(컬럼, 인덱스).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from notifications.models import Notification, NotificationPref
from notifications.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0031_notifications"
PREVIOUS = "0030_agent_cursor_drop_gap_seq"
MODELS = (Notification, NotificationPref)
TABLES = {m.__tablename__ for m in MODELS}
MIG_DB = f"{TEST_DB_NAME}_notif_mig"[:63]


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
    # alembic.ini를 넘기지 않는다 — env.py가 fileConfig로 로깅을 다시 설정해 caplog 테스트를 깨뜨린다(agent 테스트와 같은 이유)
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_chain_has_a_single_head_and_this_revision_follows_agent():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_matches_models_and_downgrade_removes_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        for model in MODELS:
            migrated = {c["name"]: (c["nullable"], str(c["type"].compile(engine.dialect)))
                        for c in inspector.get_columns(model.__tablename__)}
            declared = {c.name: (c.nullable, str(c.type.compile(engine.dialect))) for c in model.__table__.columns}
            assert migrated == declared, model.__tablename__
        assert {i["name"] for i in inspector.get_indexes("notifications")} == {
            "ix_notifications_user_created", "ix_notifications_user_unread"}
        unread = next(i for i in inspector.get_indexes("notifications") if i["name"] == "ix_notifications_user_unread")
        assert "read_at IS NULL" in unread["dialect_options"]["postgresql_where"]
        assert inspector.get_pk_constraint("notification_prefs")["constrained_columns"] == ["user_id", "type"]
        assert not inspector.get_foreign_keys("notifications")      # 지도가 삭제돼도 알림은 남는다
    finally:
        engine.dispose()

    command.downgrade(cfg, PREVIOUS)
    engine = sa.create_engine(mig_url)
    try:
        assert not TABLES & set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(cfg, REVISION)      # 다시 올려도 깨지지 않는다

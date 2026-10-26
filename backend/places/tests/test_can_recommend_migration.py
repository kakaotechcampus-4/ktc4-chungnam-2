"""마이그레이션 0040_drop_places_can_recommend up/down — 0039까지 올린 DB에서 칸을 지우고, 내리면 curated 값으로 채워 되살린다(#743).

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_cr_mig` DB를 따로 만들고 끝나면 지운다. models.py와 어긋나지 않았는지도 본다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from places.models import Place
from places.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, _replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0040_drop_places_can_recommend"
PREVIOUS = "0039_user_identities"
MIG_DB = f"{TEST_DB_NAME}_cr_mig"[:63]


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


def _can_recommend_column(url):
    engine = sa.create_engine(url)
    try:
        return {c["name"]: c for c in sa.inspect(engine).get_columns("places")}.get("can_recommend")
    finally:
        engine.dispose()


def test_chain_has_a_single_head_and_this_revision_follows_user_identities():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_drops_the_column_and_downgrade_restores_it_from_curated(mig_url):
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    assert _can_recommend_column(mig_url) is not None
    engine = sa.create_engine(mig_url)
    with engine.begin() as conn:   # 옛 규칙으로 계산된 값(curated와 어긋남)이 남아 있어도 내릴 때는 curated로 채운다
        for sid, curated, stale in (("CUR", True, False), ("PLAIN", False, True)):
            conn.execute(sa.text(
                "INSERT INTO places (id, source, source_id, name, category, geom, status, curated, can_recommend) VALUES "
                "(gen_random_uuid(), 'permit', :s, :s, '음식점', ST_GeogFromText('POINT(127 37.5)'), 'open', :c, :r)"),
                {"s": sid, "c": curated, "r": stale})
    command.upgrade(cfg, REVISION)
    assert _can_recommend_column(mig_url) is None
    assert "can_recommend" not in Place.__table__.c
    command.downgrade(cfg, PREVIOUS)
    col = _can_recommend_column(mig_url)
    assert col is not None and col["nullable"] is False and "false" in str(col["default"]).lower()
    with engine.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT source_id, can_recommend FROM places")).all())
    assert rows == {"CUR": True, "PLAIN": False}
    command.upgrade(cfg, REVISION)   # 다시 올라간다
    assert _can_recommend_column(mig_url) is None
    engine.dispose()

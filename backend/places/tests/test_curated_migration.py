"""마이그레이션 0034_places_curated up/down — 0033까지 올린 DB에서 정예 휴리스틱 되메우기가 한 번 돌고, 0033으로 내렸다가 다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_cur_mig` DB를 따로 만들고 끝나면 지운다. models.py와 어긋나지 않았는지도 본다.
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
REVISION = "0034_places_curated"
PREVIOUS = "0033_places_can_recommend"
MIG_DB = f"{TEST_DB_NAME}_cur_mig"[:63]


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


def _curated_column(url):
    engine = sa.create_engine(url)
    try:
        return {c["name"]: c for c in sa.inspect(engine).get_columns("places")}.get("curated")
    finally:
        engine.dispose()


def test_chain_has_a_single_head_and_this_revision_follows_can_recommend():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_backfills_once_with_the_label_source_heuristic_and_downgrade_drops(mig_url):
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    assert _curated_column(mig_url) is None
    engine = sa.create_engine(mig_url)
    with engine.begin() as conn:
        for sid in ("CUR", "COV", "NONE"):
            conn.execute(sa.text("INSERT INTO places (id, source, source_id, name, category, geom, status) VALUES "
                                 "(gen_random_uuid(), 'permit', :s, :s, '음식점', ST_GeogFromText('POINT(127 37.5)'), 'open')"), {"s": sid})
        for sid, src in (("CUR", None), ("COV", "license_area")):
            conn.execute(sa.text("INSERT INTO place_facts (place_id, fact_key, value, confidence, source_layer, label_source) "
                                 "SELECT id, 'k', 'true'::jsonb, 'known', 3, :src FROM places WHERE source_id = :s"), {"s": sid, "src": src})
    command.upgrade(cfg, REVISION)
    col = _curated_column(mig_url)
    assert col is not None and col["nullable"] is False and "false" in str(col["default"]).lower()
    declared = Place.__table__.c.curated
    assert declared.nullable is False and str(col["type"]) == str(declared.type.compile(engine.dialect))
    with engine.connect() as conn:
        got = dict(conn.execute(sa.text("SELECT source_id, curated FROM places")).all())
    assert got == {"CUR": True, "COV": False, "NONE": False}   # 출처 NULL 라벨이 있는 장소만 정예로 되메워진다
    command.downgrade(cfg, PREVIOUS)
    assert _curated_column(mig_url) is None
    command.upgrade(cfg, REVISION)
    assert _curated_column(mig_url) is not None
    engine.dispose()
